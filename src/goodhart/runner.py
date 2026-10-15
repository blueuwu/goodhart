"""Materialise workspaces, run verifier commands, and classify each outcome.

This is not a sandbox. Verifier commands and mutated solutions run as the
current user with the current environment. Run goodhart inside a container or
VM if the tasks are not your own.
"""

from __future__ import annotations

import difflib
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .mutants import Mutant
from .task import Snapshot, Task, Verifier


@dataclass
class RunResult:
    reward: float
    passed: bool
    exit_code: int | None
    timed_out: bool
    duration: float
    output_tail: str
    error: str = ""
    infra_error: bool = False  # the verifier could not be run or its reward could not be read


@dataclass
class MutantResult:
    mutant_id: str
    family: str
    operator: str
    description: str
    should_pass: bool
    run: RunResult
    diff: str = ""

    @property
    def evaluated(self) -> bool:
        return not self.run.infra_error

    @property
    def sound(self) -> bool:
        """True when the verifier did the right thing with this mutant (False if unevaluated)."""
        return self.evaluated and self.run.passed == self.should_pass


@dataclass
class VerifierResult:
    task: str
    verifier: str
    description: str
    gold_runs: list[RunResult]
    baseline: RunResult  # the unsolved workspace: baseline dir, or gold with stubbed functions
    mutants: list[MutantResult] = field(default_factory=list)

    @property
    def gold_ok(self) -> bool:
        return bool(self.gold_runs) and all(r.passed for r in self.gold_runs)

    @property
    def gold_flaky(self) -> bool:
        return len({r.passed for r in self.gold_runs}) > 1

    def to_json(self) -> dict:
        d = asdict(self)
        for m, raw in zip(self.mutants, d["mutants"], strict=True):
            raw["sound"] = m.sound
        d["gold_ok"] = self.gold_ok
        d["gold_flaky"] = self.gold_flaky
        return d


def mutant_diff(base: Snapshot, m: Mutant, max_lines: int = 60) -> str:
    out: list[str] = []
    for rel, data in m.edits:
        old = base.files.get(rel)
        a = old.decode("utf-8", "replace").splitlines(keepends=True) if old is not None else []
        b = data.decode("utf-8", "replace").splitlines(keepends=True) if data is not None else []
        out.extend(difflib.unified_diff(
            a, b,
            fromfile=f"a/{rel}" if old is not None else "/dev/null",
            tofile=f"b/{rel}" if data is not None else "/dev/null",
            n=1,
        ))
    lines = [ln if ln.endswith("\n") else ln + "\n" for ln in out]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)\n"]
    return "".join(lines)


def build_argv(verifier: Verifier, workspace: Path, verifier_dir: Path | None) -> list[str]:
    subs = {
        "python": sys.executable,
        "workspace": str(workspace),
        "verifier": str(verifier_dir) if verifier_dir else "",
    }
    # A string command is split POSIX-style (backslashes escape), so Windows users
    # should write `{verifier}/check.py` or give `command` as a list of arguments.
    tokens = verifier.command if isinstance(verifier.command, list) else shlex.split(verifier.command, posix=True)
    argv = []
    for tok in tokens:
        for key, val in subs.items():
            tok = tok.replace("{" + key + "}", val)
        argv.append(tok)
    return argv


def _reward(verifier: Verifier, returncode: int, stdout: str) -> tuple[float | None, str]:
    """Returns (reward, error). reward is None when the verifier's output could not be read."""
    if verifier.reward == "exit-code":
        return (1.0 if returncode == 0 else 0.0), ""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return None, "no stdout to read a reward from"
    try:
        value = float(lines[-1])
    except ValueError:
        return None, f"last stdout line is not a float: {lines[-1][:80]!r}"
    if not math.isfinite(value):
        return None, f"reward is not finite: {lines[-1][:80]!r}"
    return value, ""


def _tail(text: str, n: int = 1500) -> str:
    return text if len(text) <= n else "..." + text[-n:]


class _Job:
    """Windows Job Object: every process the verifier spawns joins it, so one call kills the tree."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        import ctypes

        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self.k32.CreateJobObjectW.restype = ctypes.c_void_p
        self.handle = self.k32.CreateJobObjectW(None, None)
        if self.handle:
            self.k32.AssignProcessToJobObject(ctypes.c_void_p(self.handle), ctypes.c_void_p(int(proc._handle)))  # type: ignore[attr-defined]

    def kill(self) -> None:
        import ctypes

        if self.handle:
            self.k32.TerminateJobObject(ctypes.c_void_p(self.handle), 1)
            self.k32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def _kill_tree(proc: subprocess.Popen[bytes], job: _Job | None) -> None:
    if job is not None:
        job.kill()
    elif os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass
    proc.wait()


def _rmtree(path: Path) -> None:
    for _ in range(5):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2)


def run_once(task: Task, verifier: Verifier, snap: Snapshot) -> RunResult:
    tmp = Path(tempfile.mkdtemp(prefix="goodhart-"))
    try:
        ws = tmp / "workspace"
        ws.mkdir()
        snap.write(ws)
        vdir = None
        if task.verifier_dir is not None:
            vdir = tmp / "verifier"
            shutil.copytree(task.verifier_dir, vdir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS")}
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONHASHSEED="0",
            GOODHART_WORKSPACE=str(ws),
            GOODHART_VERIFIER=str(vdir or ""),
        )
        argv = build_argv(verifier, ws, vdir)
        # Output goes to files, not pipes: a grandchild that inherits a pipe would
        # otherwise hold the run open past the timeout.
        out_path, err_path = tmp / "stdout.txt", tmp / "stderr.txt"
        start = time.perf_counter()
        with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
            try:
                proc = subprocess.Popen(
                    argv, cwd=ws, env=env, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                    start_new_session=(os.name != "nt"),
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            except OSError as e:
                return RunResult(0.0, False, None, False, 0.0, "", f"could not start verifier: {e}", infra_error=True)
            job = _Job(proc) if os.name == "nt" else None
            timed_out = False
            try:
                proc.wait(timeout=task.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            _kill_tree(proc, job)  # also reaps stragglers the verifier left behind
        duration = time.perf_counter() - start
        stdout = out_path.read_text(encoding="utf-8", errors="replace")
        stderr = err_path.read_text(encoding="utf-8", errors="replace")
        output = _tail(stdout + (("\n[stderr]\n" + stderr) if stderr else ""))
        if timed_out:
            return RunResult(0.0, False, None, True, duration, output, "timeout")
        reward, err = _reward(verifier, proc.returncode, stdout)
        if reward is None:
            return RunResult(0.0, False, proc.returncode, False, duration, output, err, infra_error=True)
        return RunResult(reward, reward >= verifier.threshold, proc.returncode, False, duration, output)
    finally:
        _rmtree(tmp)


def run_verifier(
    task: Task,
    verifier: Verifier,
    gold: Snapshot,
    unsolved: Snapshot,
    mutants: list[Mutant],
    gold_runs: int = 2,
    jobs: int = 4,
    progress: Callable[[str], None] | None = None,
) -> VerifierResult:
    say = progress or (lambda _: None)
    say(f"{task.name}/{verifier.name}: gold x{gold_runs}")
    golds = [run_once(task, verifier, gold) for _ in range(gold_runs)]
    baseline = run_once(task, verifier, unsolved)
    result = VerifierResult(task.name, verifier.name, verifier.description, golds, baseline)
    if not result.gold_ok:
        say(f"{task.name}/{verifier.name}: gold solution does not pass; skipping mutants")
        return result

    bases = {"gold": gold, "unsolved": unsolved}

    def one(m: Mutant) -> MutantResult:
        base = bases[m.base]
        r = MutantResult(m.id, m.family, m.operator, m.description, m.should_pass, run_once(task, verifier, m.apply(base)))
        if not r.sound:
            r.diff = mutant_diff(base, m)
        return r

    say(f"{task.name}/{verifier.name}: {len(mutants)} mutants")
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        result.mutants = list(pool.map(one, mutants))
    return result
