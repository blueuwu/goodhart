"""Materialise workspaces, run verifier commands, and classify each outcome.

This is not a sandbox. Verifier commands and mutated solutions run as the
current user with the current environment. Run goodhart inside a container or
VM if the tasks are not your own.
"""

from __future__ import annotations

import difflib
import os
import shlex
import shutil
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
    def sound(self) -> bool:
        """True when the verifier did the right thing with this mutant."""
        return self.run.passed == self.should_pass


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
    argv = []
    for tok in shlex.split(verifier.command, posix=True):
        for key, val in subs.items():
            tok = tok.replace("{" + key + "}", val)
        argv.append(tok)
    return argv


def _reward(verifier: Verifier, proc: subprocess.CompletedProcess[str]) -> tuple[float, str]:
    if verifier.reward == "exit-code":
        return (1.0 if proc.returncode == 0 else 0.0), ""
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return 0.0, "no stdout to read a reward from"
    try:
        return float(lines[-1]), ""
    except ValueError:
        return 0.0, f"last stdout line is not a float: {lines[-1][:80]!r}"


def _tail(text: str, n: int = 1500) -> str:
    return text if len(text) <= n else "..." + text[-n:]


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
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                argv, cwd=ws, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=task.timeout,
            )
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "")
            text = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            return RunResult(0.0, False, None, True, time.perf_counter() - start, _tail(text), "timeout")
        except OSError as e:
            return RunResult(0.0, False, None, False, time.perf_counter() - start, "", f"could not start verifier: {e}")
        duration = time.perf_counter() - start
        reward, err = _reward(verifier, proc)
        output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return RunResult(reward, reward >= verifier.threshold, proc.returncode, False, duration, _tail(output), err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
