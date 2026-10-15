"""Sensitivity operators: classic semantic mutants of the gold solution.

A verifier that accepts one of these is accepting a solution that behaves
differently from the reference. Some survivors are *equivalent* mutants (the
change is unobservable), so survivors are leads to review, not proven holes.
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Callable, Iterable, Iterator

from .base import (
    SENSITIVITY,
    Context,
    Mutant,
    Splicer,
    compiles,
    docstring_nodes,
    fstring_ranges,
    inside,
)

COMPARE_FLIP: dict[type, type] = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
BINOP_SWAP: dict[type, type] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult, ast.Mod: ast.FloorDiv, ast.Pow: ast.Mult,
}
COMPOUND = (ast.BinOp, ast.BoolOp, ast.Compare, ast.UnaryOp, ast.IfExp, ast.Lambda, ast.NamedExpr)

Edit = tuple[ast.AST, str]  # node whose span is replaced, replacement text


def _expr(node: ast.expr) -> str:
    text = ast.unparse(node)
    return f"({text})" if isinstance(node, COMPOUND) else text


def _skip_ids(tree: ast.Module) -> set[int]:
    """Nodes that are not behaviour: docstrings, annotations, `__main__` blocks."""
    skip = set(docstring_nodes(tree))

    def mark(n: ast.AST | None) -> None:
        if n is not None:
            skip.update(id(x) for x in ast.walk(n))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(node.returns)
            for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                mark(a.annotation)
            for a in (node.args.vararg, node.args.kwarg):
                if a is not None:
                    mark(a.annotation)
        elif isinstance(node, ast.AnnAssign):
            mark(node.annotation)
        elif (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            mark(node)
    return skip


def compare_flip(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in COMPARE_FLIP:
                    new = copy.deepcopy(node)
                    new.ops[i] = COMPARE_FLIP[type(op)]()
                    yield node, _expr(new)


def binop_swap(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and type(node.op) in BINOP_SWAP:
            new = copy.deepcopy(node)
            new.op = BINOP_SWAP[type(node.op)]()
            yield node, _expr(new)
        elif isinstance(node, ast.AugAssign) and type(node.op) in BINOP_SWAP:
            new = copy.deepcopy(node)
            new.op = BINOP_SWAP[type(node.op)]()
            yield node, ast.unparse(new)


def boolop_swap(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            new = copy.deepcopy(node)
            new.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            yield node, _expr(new)


def negate_condition(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            test = node.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                continue  # covered by remove-unary
            yield test, f"not {_expr(test)}"


def remove_unary(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.Invert)):
            yield node, _expr(node.operand)


def constant_perturb(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        v = node.value
        if isinstance(v, bool):
            yield node, repr(not v)
        elif isinstance(v, int):
            yield node, repr(v + 1)
        elif isinstance(v, float):
            yield node, repr(v + 1.0)


def string_empty(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
            yield node, '""'


def return_none(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                continue
            yield node.value, "None"


def delete_statement(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            for stmt in body:
                if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)) or (
                    isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                ):
                    if isinstance(node, ast.Module) and not isinstance(stmt, ast.AugAssign):
                        continue  # module-level bindings fail at import: trivially killed
                    yield stmt, "pass"


def break_continue(tree: ast.Module) -> Iterator[Edit]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Break):
            yield node, "continue"
        elif isinstance(node, ast.Continue):
            yield node, "break"


OPERATORS: dict[str, tuple[Callable[[ast.Module], Iterator[Edit]], str]] = {
    "compare-flip": (compare_flip, "flip a comparison operator"),
    "binop-swap": (binop_swap, "swap an arithmetic operator"),
    "boolop-swap": (boolop_swap, "swap `and`/`or`"),
    "negate-condition": (negate_condition, "negate a branch or loop condition"),
    "remove-unary": (remove_unary, "drop a `not`, `-` or `~`"),
    "constant-perturb": (constant_perturb, "bump a numeric constant or flip a bool"),
    "string-empty": (string_empty, "replace a string literal with \"\""),
    "return-none": (return_none, "return None instead of the computed value"),
    "delete-statement": (delete_statement, "replace an assignment or call statement with `pass`"),
    "break-continue": (break_continue, "swap `break`/`continue`"),
}


def generate(ctx: Context) -> Iterable[Mutant]:
    for rel, src, tree in ctx.editable_sources():
        splicer = Splicer(src)
        skip = _skip_ids(tree)
        fstrings = fstring_ranges(tree)
        seen: set[str] = set()
        for op_name, (fn, desc) in OPERATORS.items():
            counts: dict[tuple[int, int], int] = {}
            for node, text in fn(tree):
                if id(node) in skip or inside(node, fstrings):
                    continue
                a, b = splicer.span(node)
                new_src = splicer.replace([(a, b, text)])
                if new_src == src or new_src in seen or not compiles(new_src):
                    continue
                seen.add(new_src)
                pos = (node.lineno, node.col_offset + 1)  # type: ignore[attr-defined]
                n = counts[pos] = counts.get(pos, 0) + 1
                suffix = f"#{n}" if n > 1 else ""
                before = splicer.segment(node).splitlines()[0]
                yield Mutant(
                    id=f"{op_name}:{rel}:{pos[0]}:{pos[1]}{suffix}",
                    family=SENSITIVITY,
                    operator=op_name,
                    description=f"{desc}: `{_clip(before)}` -> `{_clip(text)}`",
                    edits=((rel, new_src.encode("utf-8")),),
                )


def _clip(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."
