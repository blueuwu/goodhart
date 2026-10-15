from __future__ import annotations

import ast
import random

from ..task import Snapshot, Task
from . import hacks, invariance, sensitivity
from .base import FAMILIES, HACK, INVARIANCE, SENSITIVITY, Context, Mutant, Splicer, docstring_nodes

__all__ = ["FAMILIES", "HACK", "INVARIANCE", "SENSITIVITY", "Mutant", "generate_all", "unsolved_snapshot"]

GENERATORS = {SENSITIVITY: sensitivity.generate, HACK: hacks.generate, INVARIANCE: invariance.generate}


def stub_functions(src: str) -> str:
    """Replace the body of every outermost function with `raise NotImplementedError`."""
    tree = ast.parse(src)
    sp = Splicer(src)
    docs = docstring_nodes(tree)
    reps = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [s for s in child.body if not (isinstance(s, ast.Expr) and id(s.value) in docs)]
                if body:
                    reps.append((sp.span(body[0])[0], sp.span(body[-1])[1], "raise NotImplementedError"))
            elif isinstance(child, ast.ClassDef):
                visit(child)

    visit(tree)
    return sp.replace(reps)


def unsolved_snapshot(task: Task, gold: Snapshot) -> Snapshot:
    """The task's baseline if it has one, else gold with every editable function stubbed."""
    if task.baseline is not None:
        return Snapshot.read(task.baseline)
    ctx = Context(task=task, source=gold)
    files = dict(gold.files)
    for rel, src, _ in ctx.editable_sources():
        files[rel] = stub_functions(src).encode("utf-8")
    return Snapshot(files)


def generate_all(
    task: Task,
    gold: Snapshot,
    families: tuple[str, ...] = FAMILIES,
    operators: set[str] | None = None,
    max_per_operator: int | None = None,
    seed: int = 0,
    unsolved: Snapshot | None = None,
) -> list[Mutant]:
    if unsolved is None:
        unsolved = unsolved_snapshot(task, gold)
    out: list[Mutant] = []
    for fam in families:
        ctx = Context(task=task, source=unsolved if fam == HACK else gold)
        by_op: dict[str, list[Mutant]] = {}
        for m in GENERATORS[fam](ctx):
            if operators is None or m.operator in operators:
                by_op.setdefault(m.operator, []).append(m)
        for op, ms in by_op.items():
            if max_per_operator is not None and len(ms) > max_per_operator:
                rng = random.Random(f"{seed}:{task.name}:{op}")
                keep = {id(m) for m in rng.sample(ms, max_per_operator)}
                ms = [m for m in ms if id(m) in keep]
            out.extend(ms)
    return out
