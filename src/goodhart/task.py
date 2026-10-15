"""Task definitions: a gold solution, an optional baseline, and one or more verifiers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import globs

REWARD_MODES = ("exit-code", "stdout-float")
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}


class TaskError(ValueError):
    pass


@dataclass(frozen=True)
class Verifier:
    name: str
    command: str
    reward: str = "exit-code"
    threshold: float = 1.0
    description: str = ""


@dataclass(frozen=True)
class Task:
    name: str
    root: Path
    solution: Path
    baseline: Path | None
    verifier_dir: Path | None
    editable: tuple[str, ...]
    writable: tuple[str, ...]
    visible_tests: tuple[str, ...]
    timeout: float
    verifiers: tuple[Verifier, ...]
    description: str = ""

    def is_editable(self, rel: str) -> bool:
        return globs.match(rel, self.editable)

    def is_writable(self, rel: str) -> bool:
        return globs.match(rel, self.writable)

    def is_visible_test(self, rel: str) -> bool:
        return globs.match(rel, self.visible_tests)


@dataclass
class Snapshot:
    """In-memory copy of a workspace: POSIX relative path -> bytes."""

    files: dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def read(cls, root: Path) -> Snapshot:
        files: dict[str, bytes] = {}
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts) or p.suffix == ".pyc":
                continue
            if p.is_file():
                files[rel.as_posix()] = p.read_bytes()
        return cls(files)

    def write(self, root: Path) -> None:
        for rel, data in self.files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

    def text(self, rel: str) -> str:
        return self.files[rel].decode("utf-8")


def _str_list(raw: object, key: str, default: list[str]) -> tuple[str, ...]:
    if raw is None:
        return tuple(default)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise TaskError(f"`{key}` must be a string or list of strings")
    return tuple(raw)


def load_task(path: Path) -> Task:
    path = Path(path)
    toml_path = path / "task.toml" if path.is_dir() else path
    root = toml_path.parent.resolve()
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise TaskError(f"no task.toml at {toml_path}") from e
    except tomllib.TOMLDecodeError as e:
        raise TaskError(f"{toml_path}: {e}") from e

    def subdir(key: str, required: bool) -> Path | None:
        val = data.get(key)
        if val is None:
            if required:
                raise TaskError(f"{toml_path}: `{key}` is required")
            return None
        p = (root / val).resolve()
        if not p.is_dir():
            raise TaskError(f"{toml_path}: `{key}` = {val!r} is not a directory")
        return p

    raw_verifiers = data.get("verifiers")
    if not isinstance(raw_verifiers, dict) or not raw_verifiers:
        raise TaskError(f"{toml_path}: at least one [verifiers.<name>] table is required")
    verifiers = []
    for vname, v in raw_verifiers.items():
        if not isinstance(v, dict) or not isinstance(v.get("command"), str):
            raise TaskError(f"{toml_path}: verifiers.{vname}.command must be a string")
        reward = v.get("reward", "exit-code")
        if reward not in REWARD_MODES:
            raise TaskError(f"{toml_path}: verifiers.{vname}.reward must be one of {REWARD_MODES}")
        verifiers.append(
            Verifier(
                name=vname,
                command=v["command"],
                reward=reward,
                threshold=float(v.get("threshold", 1.0)),
                description=str(v.get("description", "")),
            )
        )

    return Task(
        name=str(data.get("name", root.name)),
        root=root,
        solution=subdir("solution", True),  # type: ignore[arg-type]
        baseline=subdir("baseline", False),
        verifier_dir=subdir("verifier_dir", False),
        editable=_str_list(data.get("editable"), "editable", ["**/*.py"]),
        writable=_str_list(data.get("writable"), "writable", ["**"]),
        visible_tests=_str_list(
            data.get("visible_tests"), "visible_tests", ["**/test_*.py", "**/*_test.py"]
        ),
        timeout=float(data.get("timeout", 60)),
        verifiers=tuple(verifiers),
        description=str(data.get("description", "")),
    )


def discover_tasks(paths: list[Path]) -> list[Task]:
    tasks: list[Task] = []
    for path in paths:
        path = Path(path)
        if (path / "task.toml").is_file() or path.is_file():
            tasks.append(load_task(path))
        elif path.is_dir():
            found = sorted(path.rglob("task.toml"))
            if not found:
                raise TaskError(f"no task.toml found under {path}")
            tasks.extend(load_task(p) for p in found)
        else:
            raise TaskError(f"{path} does not exist")
    return tasks
