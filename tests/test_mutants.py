import ast
import importlib.util
import random
import sys
from pathlib import Path

import pytest

from goodhart import globs
from goodhart.mutants import HACK, INVARIANCE, SENSITIVITY, generate_all
from goodhart.mutants.base import Splicer
from goodhart.task import Snapshot, load_task

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "tasks"


@pytest.mark.parametrize(
    "path, patterns, expected",
    [
        ("a.py", ["*.py"], True),
        ("pkg/a.py", ["*.py"], False),
        ("pkg/a.py", ["**/*.py"], True),
        ("a.py", ["**/*.py"], True),
        ("tests/x/test_a.py", ["tests/**"], True),
        ("tests_a.py", ["tests/**"], False),
        ("conftest.py", ["src/**"], False),
    ],
)
def test_globs(path, patterns, expected):
    assert globs.match(path, patterns) is expected


def test_splicer_handles_multibyte_columns():
    src = 'x = "é" + 1\n'
    tree = ast.parse(src)
    binop = tree.body[0].value
    sp = Splicer(src)
    assert sp.segment(binop) == '"é" + 1'
    assert sp.replace([(*sp.span(binop.right), "2")]) == 'x = "é" + 2\n'


def _task(name):
    task = load_task(EXAMPLES / name)
    return task, Snapshot.read(task.solution)


@pytest.mark.parametrize("name", ["slugify", "intervals", "roman"])
def test_every_mutant_is_distinct_and_compiles(name):
    task, gold = _task(name)
    mutants = generate_all(task, gold)
    assert len({m.id for m in mutants}) == len(mutants)
    fams = {m.family for m in mutants}
    assert fams == {SENSITIVITY, HACK, INVARIANCE}
    for m in mutants:
        snap = m.apply(gold)
        assert snap.files != gold.files, m.id
        for rel, data in m.edits:
            if data is not None and rel.endswith(".py"):
                compile(data, rel, "exec")


def _load(module_name, source, tmp_path, tag):
    path = tmp_path / tag / f"{module_name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"{module_name}_{tag}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CASES = {
    "slugify": lambda rng: [
        ("slugify", (rng.choice(["Hello World", "  a  b ", "Café!", "x" * 60, "one two three four", ""]),),
         {"max_length": rng.randint(1, 30)})
        for _ in range(50)
    ],
    "intervals": lambda rng: [
        (fn, (sorted_pairs(rng),) + extra, {})
        for _ in range(60)
        for fn, extra in [("merge", ()), ("total_length", ()), ("gaps", (rng.randint(-5, 5), rng.randint(5, 25)))]
    ],
    "roman": lambda rng: [("to_roman", (rng.randint(1, 3999),), {}) for _ in range(100)],
}


def sorted_pairs(rng):
    out = []
    for _ in range(rng.randint(0, 5)):
        a = rng.randint(-10, 20)
        out.append((a, a + rng.randint(0, 6)))
    return out


def _call(mod, fn, args, kwargs):
    try:
        return ("ok", getattr(mod, fn)(*args, **kwargs))
    except Exception as e:  # noqa: BLE001
        return ("err", type(e).__name__)


@pytest.mark.parametrize("name", ["slugify", "intervals", "roman"])
def test_invariance_mutants_preserve_behaviour(name, tmp_path):
    task, gold = _task(name)
    module = task.editable[0]
    gold_mod = _load(module[:-3], gold.text(module), tmp_path, "gold")
    cases = CASES[name](random.Random(0))
    invariants = [m for m in generate_all(task, gold, families=(INVARIANCE,)) if module in dict(m.edits)]
    assert invariants
    for i, m in enumerate(invariants):
        mod = _load(module[:-3], m.apply(gold).text(module), tmp_path, f"m{i}")
        for fn, args, kwargs in cases:
            assert _call(mod, fn, args, kwargs) == _call(gold_mod, fn, args, kwargs), (m.id, fn, args)


def test_memorize_hack_reproduces_visible_cases_only(tmp_path):
    task, gold = _task("roman")
    (m,) = [m for m in generate_all(task, gold, families=(HACK,)) if m.operator == "memorize-visible-tests"]
    mod = _load("roman", m.apply(gold).text("roman.py"), tmp_path, "memo")
    assert mod.to_roman(1994) == "MCMXCIV"
    assert mod.from_roman("XLII") == 42
    assert mod.to_roman(1995) is None


def test_hacks_respect_writable(tmp_path):
    task, gold = _task("slugify")
    from dataclasses import replace

    locked = replace(task, writable=("slugify.py",))
    ops = {m.operator for m in generate_all(locked, gold, families=(HACK,))}
    assert "conftest-force-pass" not in ops and "delete-tests" not in ops and "shadow-pytest" not in ops
    assert {"memorize-visible-tests", "import-exit0", "atexit-exit0"} <= ops


def test_max_per_operator_is_deterministic():
    task, gold = _task("roman")
    a = [m.id for m in generate_all(task, gold, max_per_operator=2, seed=7)]
    b = [m.id for m in generate_all(task, gold, max_per_operator=2, seed=7)]
    assert a == b
    from collections import Counter

    assert max(Counter(i.split(":")[0] for i in a).values()) <= 2


def test_python_is_running_tests_on_311_plus():
    assert sys.version_info >= (3, 11)


def _invariants_for(src, tmp_path):
    from goodhart.task import Task

    (tmp_path / "solution").mkdir(exist_ok=True)
    task = Task(
        name="t", root=tmp_path, solution=tmp_path / "solution", baseline=None, verifier_dir=None,
        editable=("m.py",), writable=("**",), visible_tests=("tests/**",), timeout=10, verifiers=(),
    )
    return generate_all(task, Snapshot({"m.py": src.encode()}), families=(INVARIANCE,))


def test_rename_locals_leaves_comprehension_shadowed_globals_alone(tmp_path):
    src = "x = 10\n\ndef f(ys):\n    out = [x for x in ys]\n    return out, x\n"
    for m in _invariants_for(src, tmp_path):
        if m.operator == "rename-locals":
            new = dict(m.edits)["m.py"].decode()
            ns_a, ns_b = {}, {}
            exec(src, ns_a)
            exec(new, ns_b)
            assert ns_a["f"]([1, 2]) == ns_b["f"]([1, 2])


def test_rename_locals_does_not_touch_defaults(tmp_path):
    src = "y = 5\n\ndef f(a=y):\n    y = a + 1\n    return y\n"
    (m,) = [m for m in _invariants_for(src, tmp_path) if m.operator == "rename-locals"]
    new = dict(m.edits)["m.py"].decode()
    assert "def f(a=y):" in new and "y_ = a + 1" in new


def test_reorder_skips_runs_with_definition_time_calls(tmp_path):
    src = "log = []\n\ndef a(x=log.append(1)):\n    pass\n\ndef b(x=log.append(2)):\n    pass\n"
    assert not [m for m in _invariants_for(src, tmp_path) if m.operator == "reorder-functions"]


def test_stub_functions_keeps_docstrings():
    from goodhart.mutants import stub_functions

    out = stub_functions('def f(x):\n    """Doc."""\n    y = x\n    return y\n\nclass C:\n    def g(self):\n        return 1\n')
    assert '"""Doc."""' in out
    assert out.count("raise NotImplementedError") == 2
    compile(out, "m", "exec")
