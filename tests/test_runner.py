"""End-to-end runs on a tiny task whose verifiers are plain Python scripts (fast, no pytest child)."""

import json
import textwrap
from pathlib import Path

import pytest

from goodhart.cli import main
from goodhart.mutants import generate_all, unsolved_snapshot
from goodhart.report import render_markdown, scores
from goodhart.runner import run_verifier
from goodhart.task import Snapshot, TaskError, load_task


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


@pytest.fixture
def tiny(tmp_path):
    write(tmp_path, {
        "solution/calc.py": """
            def clamp(x, lo, hi):
                if x < lo:
                    return lo
                if x > hi:
                    return hi
                return x
        """,
        "baseline/calc.py": """
            def clamp(x, lo, hi):
                return x
        """,
        "verifier/strict.py": """
            import sys
            sys.path.insert(0, sys.argv[1])
            from calc import clamp
            cases = [((5, 0, 10), 5), ((-1, 0, 10), 0), ((11, 0, 10), 10), ((0, 0, 10), 0), ((10, 0, 10), 10)]
            ok = sum(clamp(*a) == b for a, b in cases)
            print(ok / len(cases))
        """,
        "verifier/weak.py": """
            import sys
            sys.path.insert(0, sys.argv[1])
            from calc import clamp
            sys.exit(0 if clamp(5, 0, 10) == 5 else 1)
        """,
        "verifier/vacuous.py": """
            print(1.0)
        """,
        "task.toml": """
            name = "tiny"
            solution = "solution"
            baseline = "baseline"
            verifier_dir = "verifier"
            editable = ["calc.py"]
            timeout = 20

            [verifiers.strict]
            command = "{python} {verifier}/strict.py {workspace}"
            reward = "stdout-float"

            [verifiers.weak]
            command = "{python} {verifier}/weak.py {workspace}"

            [verifiers.vacuous]
            command = "{python} {verifier}/vacuous.py"
            reward = "stdout-float"
        """,
    })
    return tmp_path


def _run(root, name, families=("sensitivity", "invariance")):
    task = load_task(root)
    gold = Snapshot.read(task.solution)
    unsolved = unsolved_snapshot(task, gold)
    mutants = generate_all(task, gold, families=families, unsolved=unsolved)
    (v,) = [v for v in task.verifiers if v.name == name]
    return run_verifier(task, v, gold, unsolved, mutants, gold_runs=1, jobs=4)


def test_strict_verifier_kills_mutants(tiny):
    vr = _run(tiny, "strict")
    sc = scores(vr)
    assert vr.gold_ok and not vr.baseline.passed
    assert sc["sensitivity"].total >= 6
    # `x < lo` -> `x <= lo` (and the `hi` twin) return the same value: equivalent mutants.
    survivors = sorted(m.description for m in vr.mutants if m.family == "sensitivity" and not m.sound)
    assert survivors == [
        "flip a comparison operator: `x < lo` -> `(x <= lo)`",
        "flip a comparison operator: `x > hi` -> `(x >= hi)`",
    ]
    assert sc["invariance"].good == sc["invariance"].total


def test_weak_verifier_lets_mutants_survive(tiny):
    vr = _run(tiny, "weak")
    sc = scores(vr)
    assert sc["sensitivity"].good < sc["sensitivity"].total
    survivors = [m for m in vr.mutants if m.family == "sensitivity" and not m.sound]
    assert all(m.diff.startswith("---") for m in survivors)
    md = render_markdown([vr])
    assert "Surviving mutants" in md


def test_exit_hijack_beats_exit_code_but_not_stdout_reward(tiny):
    weak = _run(tiny, "weak", families=("hack",))
    strict = _run(tiny, "strict", families=("hack",))
    by_op = {m.operator: m for m in weak.mutants}
    assert by_op["import-exit0"].run.passed
    assert not {m.operator: m for m in strict.mutants}["import-exit0"].run.passed


def test_vacuous_verifier_flagged(tiny):
    vr = _run(tiny, "vacuous")
    assert vr.baseline.passed
    assert "vacuous" in render_markdown([vr])


def test_cli_writes_reports_and_sets_exit_code(tiny, tmp_path):
    out = tmp_path / "out"
    code = main(["run", str(tiny), "--verifier", "weak", "--gold-runs", "1", "-q", "--out", str(out),
                 "--min-sensitivity", "1.0"])
    assert code == 1
    data = json.loads((out / "results.json").read_text())
    assert data["verifiers"][0]["verifier"] == "weak"
    assert (out / "report.md").read_text().startswith("# goodhart report")

    assert main(["run", str(tiny), "--verifier", "strict", "--gold-runs", "1", "-q", "--families", "sensitivity",
                 "--min-sensitivity", "0.7"]) == 0


def test_gold_failure_is_invalid_task(tiny):
    (tiny / "verifier" / "weak.py").write_text("raise SystemExit(1)\n")
    assert main(["run", str(tiny), "--verifier", "weak", "--gold-runs", "1", "-q"]) == 3


def test_bad_task_toml(tmp_path):
    (tmp_path / "task.toml").write_text('solution = "nope"\n[verifiers.a]\ncommand = "x"\n')
    with pytest.raises(TaskError):
        load_task(tmp_path)
    assert main(["run", str(tmp_path), "-q"]) == 2


def test_render_round_trips_results_json(tiny, tmp_path):
    out = tmp_path / "out"
    # exit 1: the weak verifier also accepts the unsolved baseline, so it is flagged vacuous
    assert main(["run", str(tiny), "--verifier", "weak", "--gold-runs", "1", "-q", "--out", str(out),
                 "--families", "sensitivity"]) == 1
    before = (out / "report.md").read_text()
    (out / "report.md").unlink()
    assert main(["render", str(out / "results.json")]) == 0
    assert (out / "report.md").read_text() == before
    assert "<table>" in (out / "report.html").read_text()
