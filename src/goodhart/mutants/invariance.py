"""Invariance operators: rewrites that keep behaviour the same.

A verifier that rejects one of these is grading the shape of the reference
solution, not what it does, so it will also reject valid alternative solutions.

"Behaviour" here means what the code computes. Code that reads its own source
(`inspect.getsource`, `open(__file__)`) can tell a comment was added or the
file reformatted; for such solutions those operators are not invariant.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from .base import INVARIANCE, Context, Mutant, Splicer, compiles

UNSAFE_CALLS = {"locals", "vars", "eval", "exec", "globals"}


def _mutant(ctx: Context, op: str, target: str, desc: str, edits: list[tuple[str, bytes | None]]) -> Mutant | None:
    if not edits or not all(ctx.task.is_writable(rel) for rel, _ in edits):
        return None
    return Mutant(id=f"{op}:{target}", family=INVARIANCE, operator=op, description=desc, edits=tuple(edits))


def _same_ast(a: str, b: str) -> bool:
    try:
        return ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))
    except (SyntaxError, ValueError, RecursionError):
        return False


def reformat(ctx: Context) -> Iterable[Mutant]:
    for rel, src, tree in ctx.editable_sources():
        try:
            new = ast.unparse(tree) + "\n"
        except (ValueError, RecursionError):  # e.g. int literals past the str-conversion limit
            continue
        # ast.unparse does not round-trip everything (NFKC-normalised identifiers can
        # turn into keywords), so only keep output that parses back to the same tree.
        if new != src and _same_ast(src, new):
            m = _mutant(ctx, "reformat", rel, "re-emit the module through ast.unparse (drops comments, normalises quoting and spacing)", [(rel, new.encode())])
            if m:
                yield m


def _body_nodes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Nodes in the function body only: defaults, annotations and decorators are
    evaluated in the enclosing scope and must not be renamed."""
    return [n for stmt in fn.body for n in ast.walk(stmt)]


IDENT_FIELDS = ("id", "arg", "name", "asname", "attr")


def _identifiers(tree: ast.AST) -> set[str]:
    """Every identifier the module spells anywhere, so fresh names never collide."""
    out: set[str] = set()
    for node in ast.walk(tree):
        for field in IDENT_FIELDS:
            val = getattr(node, field, None)
            if isinstance(val, str):
                out.update(val.split("."))
        names = getattr(node, "names", None)
        if isinstance(names, list):
            out.update(n for n in names if isinstance(n, str))
    return out


def _renameable(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    params |= {a.arg for a in (fn.args.vararg, fn.args.kwarg) if a is not None}
    stored: set[str] = set()
    excluded: set[str] = set()
    for node in _body_nodes(fn):
        if isinstance(node, ast.comprehension):
            # Comprehension targets live in their own scope and may shadow a global
            # the function also reads, so renaming every occurrence is not safe.
            excluded.update(n.id for n in ast.walk(node.target) if isinstance(n, ast.Name))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.JoinedStr, ast.Match)):
            return set()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in UNSAFE_CALLS:
            return set()
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            excluded.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            excluded.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            excluded.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stored.add(node.id)
    # Dunder-prefixed names are mangled inside classes, and `__class__` feeds
    # zero-argument super(); neither survives a rename unchanged.
    return {n for n in stored - params - excluded if not n.startswith("__")}


def rename_locals(ctx: Context) -> Iterable[Mutant]:
    for rel, src, tree in ctx.editable_sources():
        taken = _identifiers(tree)
        sp = Splicer(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = _renameable(fn)
            if not names:
                continue
            mapping = {}
            for name in sorted(names):
                new = f"{name}_"
                while new in taken:
                    new += "_"
                taken.add(new)
                mapping[name] = new
            reps = [
                (*sp.span(n), mapping[n.id])
                for n in _body_nodes(fn)
                if isinstance(n, ast.Name) and n.id in mapping
            ]
            new_src = sp.replace(reps)
            if compiles(new_src):
                pairs = ", ".join(f"{a}->{b}" for a, b in mapping.items())
                m = _mutant(ctx, "rename-locals", f"{rel}:{fn.name}", f"rename locals in `{fn.name}` ({pairs})", [(rel, new_src.encode())])
                if m:
                    yield m


SAFE_DEF_TIME = (
    ast.Constant, ast.Name, ast.Attribute, ast.Subscript, ast.Tuple, ast.Load,
    ast.UnaryOp, ast.USub, ast.UAdd, ast.BinOp, ast.BitOr,
)


def _def_time_unsafe(node: ast.FunctionDef) -> bool:
    """Defaults and annotations run at definition time. Reordering is only safe when
    they are plain names, constants and `X | Y` / `X[Y]` type expressions."""
    for e in _def_time_exprs(node):
        for n in ast.walk(e):
            if not isinstance(n, SAFE_DEF_TIME):
                return True
            if isinstance(n, ast.BinOp) and not isinstance(n.op, ast.BitOr):
                return True
    return False


def _free_refs(node: ast.FunctionDef) -> set[str]:
    """Names evaluated when the `def` statement itself runs."""
    return {n.id for e in _def_time_exprs(node) for n in ast.walk(e) if isinstance(n, ast.Name)}


def _def_time_exprs(node: ast.FunctionDef) -> list[ast.AST]:
    exprs: list[ast.AST] = [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]
    if node.returns:
        exprs.append(node.returns)
    for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
        if a.annotation:
            exprs.append(a.annotation)
    for a in (node.args.vararg, node.args.kwarg):
        if a is not None and a.annotation:
            exprs.append(a.annotation)
    return exprs


def reorder_functions(ctx: Context) -> Iterable[Mutant]:
    for rel, src, tree in ctx.editable_sources():
        runs: list[list[ast.FunctionDef]] = [[]]
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef) and not stmt.decorator_list:
                runs[-1].append(stmt)
            elif runs[-1]:
                runs.append([])
        sp = Splicer(src)
        reps = []
        for run in runs:
            if len(run) < 2:
                continue
            names = {f.name for f in run}
            if len(names) < len(run):
                continue  # a later duplicate def wins; reordering would change which one
            if any(_free_refs(f) & names or _def_time_unsafe(f) for f in run):
                continue
            texts = [sp.segment(f) for f in run]
            for f, text in zip(run, reversed(texts), strict=True):
                reps.append((*sp.span(f), text))
        if reps:
            new_src = sp.replace(reps)
            if new_src != src and compiles(new_src):
                m = _mutant(ctx, "reorder-functions", rel, "reverse the order of consecutive top-level function definitions", [(rel, new_src.encode())])
                if m:
                    yield m


def append_comment(ctx: Context) -> Iterable[Mutant]:
    edits: list[tuple[str, bytes | None]] = [
        (rel, (src.rstrip("\n") + "\n\n# Reviewed: behaviour unchanged.\n").encode())
        for rel, src, _ in ctx.editable_sources()
    ]
    m = _mutant(ctx, "append-comment", "editable-modules", "append a trailing comment to each editable module", edits)
    if m:
        yield m


def add_notes_file(ctx: Context) -> Iterable[Mutant]:
    if "NOTES.md" not in ctx.source.files:
        m = _mutant(ctx, "add-notes-file", "NOTES.md", "add an unrelated NOTES.md to the workspace", [("NOTES.md", b"# Notes\n\nWorking notes from the agent.\n")])
        if m:
            yield m


def generate(ctx: Context) -> Iterable[Mutant]:
    for op in (reformat, rename_locals, reorder_functions, append_comment, add_notes_file):
        yield from op(ctx)
