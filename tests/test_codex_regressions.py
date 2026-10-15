"""Counterexamples from an independent review (Codex, GPT-6.1 Sol). Each must stay fixed."""

import ast

import pytest

from goodhart.mutants import INVARIANCE, SENSITIVITY, generate_all
from goodhart.mutants.base import Splicer
from goodhart.runner import RunResult, _reward
from goodhart.task import Snapshot, Task, Verifier


def _task(tmp_path):
    return Task(
        name="t", root=tmp_path, solution=tmp_path, baseline=None, verifier_dir=None,
        editable=("m.py",), writable=("**",), visible_tests=("tests/**",), timeout=10, verifiers=(),
    )


def _mutants(src, tmp_path, fam):
    return generate_all(_task(tmp_path), Snapshot({"m.py": src.encode()}), families=(fam,))


def _run(src, expr):
    ns = {"__file__": "m.py"}
    exec(compile(src, "m.py", "exec"), ns)
    try:
        return ("ok", eval(expr, ns))
    except Exception as e:  # noqa: BLE001
        return ("err", type(e).__name__)


INVARIANCE_CASES = [
    # fresh name collides with an except-as binding
    ("def f():\n x=1\n try: 1/0\n except Exception as x_: pass\n return x\n", "f()"),
    # fresh name collides with a mangled parameter
    ("class C:\n def f(self, _C__x_=2):\n  __x=1\n  return _C__x_\n", "C().f()"),
    # local __class__ changes zero-argument super()
    ("class A:\n def f(self):\n  __class__=int\n  try:\n   super(); return 1\n  except RuntimeError:\n   return 0\n", "A().f()"),
    # duplicate defs: the later one wins
    ("def f(): return 1\ndef f(): return 2\n", "f()"),
    # walrus in a default runs at definition time
    ("def f(x=(y:=1)): return x\ndef g(x=(y:=2)): return x\nresult=y\n", "result"),
    # NFKC-normalised identifier that unparses to a keyword
    ("\U0001d68d\U0001d68e\U0001d68f=7\nresult=\U0001d68d\U0001d68e\U0001d68f\n", "result"),
]


@pytest.mark.parametrize("src, expr", INVARIANCE_CASES)
def test_invariance_preserves_behaviour(src, expr, tmp_path):
    want = _run(src, expr)
    for m in _mutants(src, tmp_path, INVARIANCE):
        if m.operator in ("append-comment", "add-notes-file"):
            continue
        assert _run(dict(m.edits)["m.py"].decode(), expr) == want, m.id


def test_huge_int_literal_does_not_abort_generation(tmp_path):
    src = "def f(x):\n    return x + 0x" + "f" * 4000 + "\n\ndef g(a, b):\n    return a < b\n"
    ops = {m.operator for m in _mutants(src, tmp_path, SENSITIVITY)}
    assert "compare-flip" in ops
    _mutants(src, tmp_path, INVARIANCE)


def test_nonfinite_float_not_perturbed_into_a_name(tmp_path):
    for m in _mutants("def f():\n    return 1e309\n", tmp_path, SENSITIVITY):
        assert "inf" not in dict(m.edits)["m.py"].decode()


def test_splicer_handles_lone_cr():
    src = "def f(x):\r    return x+1\n" + "\n" * 30
    tree = ast.parse(src)
    binop = tree.body[0].body[0].value
    sp = Splicer(src)
    assert sp.segment(binop) == "x+1"


@pytest.mark.parametrize("stdout", ["oops", "inf", "nan", ""])
def test_unreadable_reward_is_not_a_pass(stdout):
    v = Verifier("v", "x", reward="stdout-float", threshold=0.0)
    reward, err = _reward(v, 0, stdout)
    assert reward is None and err


def test_infra_errors_are_excluded_from_scores():
    from goodhart.report import scores
    from goodhart.runner import MutantResult, VerifierResult

    ok = RunResult(1.0, True, 0, False, 0.1, "")
    broken = RunResult(0.0, False, None, False, 0.0, "", "could not start verifier", infra_error=True)
    vr = VerifierResult("t", "v", "", [ok], RunResult(0.0, False, 1, False, 0.1, ""))
    vr.mutants = [MutantResult("a", "sensitivity", "op", "", False, broken)]
    assert scores(vr)["sensitivity"].total == 0


def test_list_command_keeps_backslashes(tmp_path):
    from goodhart.runner import build_argv

    v = Verifier("v", ["{python}", r"C:\tools\check.py"])
    assert build_argv(v, tmp_path, None)[1] == r"C:\tools\check.py"
