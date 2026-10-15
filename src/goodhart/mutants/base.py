"""Mutant model and source-splicing helpers shared by every operator family."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..task import Snapshot, Task

SENSITIVITY = "sensitivity"  # broken solution: a sound verifier rejects it
HACK = "hack"  # reward hack: a sound verifier rejects it
INVARIANCE = "invariance"  # meaning-preserving rewrite: a sound verifier accepts it
FAMILIES = (SENSITIVITY, HACK, INVARIANCE)


@dataclass(frozen=True)
class Mutant:
    id: str
    family: str
    operator: str
    description: str
    edits: tuple[tuple[str, bytes | None], ...]  # (path, new bytes | None to delete)
    base: str = "gold"  # "gold", or "unsolved" for hacks, so reward can only come from the hack

    @property
    def should_pass(self) -> bool:
        return self.family == INVARIANCE

    def apply(self, snap: Snapshot) -> Snapshot:
        files = dict(snap.files)
        for rel, data in self.edits:
            if data is None:
                files.pop(rel, None)
            else:
                files[rel] = data
        return Snapshot(files)


@dataclass
class Context:
    task: Task
    source: Snapshot  # the snapshot operators read and edit: gold, or unsolved for hacks

    def python_files(self, pred: Callable[[str], bool]) -> Iterable[tuple[str, str, ast.Module]]:
        for rel in sorted(self.source.files):
            if not rel.endswith(".py") or not pred(rel):
                continue
            try:
                src = self.source.text(rel)
                tree = ast.parse(src)
            except (UnicodeDecodeError, SyntaxError):
                continue
            yield rel, src, tree

    def editable_sources(self) -> Iterable[tuple[str, str, ast.Module]]:
        return self.python_files(lambda r: self.task.is_editable(r) and not self.task.is_visible_test(r))


Operator = Callable[[Context], Iterable[Mutant]]


class Splicer:
    """Replace spans of a source file addressed by AST positions.

    AST column offsets are UTF-8 byte offsets, so all splicing is done on bytes.
    """

    def __init__(self, src: str) -> None:
        self.data = src.encode("utf-8")
        self.line_starts = [0]
        for i, b in enumerate(self.data):
            if b == 0x0A:
                self.line_starts.append(i + 1)

    def offset(self, lineno: int, col: int) -> int:
        return self.line_starts[lineno - 1] + col

    def span(self, node: ast.AST) -> tuple[int, int]:
        return (
            self.offset(node.lineno, node.col_offset),  # type: ignore[attr-defined]
            self.offset(node.end_lineno, node.end_col_offset),  # type: ignore[attr-defined]
        )

    def segment(self, node: ast.AST) -> str:
        a, b = self.span(node)
        return self.data[a:b].decode("utf-8")

    def replace(self, replacements: list[tuple[int, int, str]]) -> str:
        out = self.data
        for a, b, text in sorted(replacements, key=lambda r: r[0], reverse=True):
            out = out[:a] + text.encode("utf-8") + out[b:]
        return out.decode("utf-8")


def compiles(src: str) -> bool:
    try:
        compile(src, "<mutant>", "exec")
    except (SyntaxError, ValueError):
        return False
    return True


def fstring_ranges(tree: ast.AST) -> list[tuple[int, int, int, int]]:
    """Positions inside f-strings are unreliable before 3.12; operators skip them."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    return out


def inside(node: ast.AST, ranges: list[tuple[int, int, int, int]]) -> bool:
    if not hasattr(node, "lineno"):
        return False
    start = (node.lineno, node.col_offset)  # type: ignore[attr-defined]
    return any((r[0], r[1]) <= start < (r[2], r[3]) for r in ranges)


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids
