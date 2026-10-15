"""goodhart command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .mutants import FAMILIES, generate_all, unsolved_snapshot
from .report import render_markdown, scores, status, summary_json
from .runner import run_verifier
from .task import Snapshot, TaskError, discover_tasks

EXIT_OK, EXIT_BELOW_THRESHOLD, EXIT_USAGE, EXIT_INVALID_TASK = 0, 1, 2, 3


def _families(raw: str) -> tuple[str, ...]:
    fams = tuple(x.strip() for x in raw.split(",") if x.strip())
    bad = [f for f in fams if f not in FAMILIES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown family {bad[0]!r}; choose from {', '.join(FAMILIES)}")
    return fams


def _rate(raw: str) -> float:
    v = float(raw)
    if not 0 <= v <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="goodhart", description="Mutation testing for RL verifiers and reward functions.")
    p.add_argument("--version", action="version", version=f"goodhart {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="score verifiers against generated mutants")
    run.add_argument("paths", nargs="+", type=Path, help="task directories, task.toml files, or folders to search")
    run.add_argument("--verifier", action="append", help="only run verifiers with this name (repeatable)")
    run.add_argument("--families", type=_families, default=FAMILIES, help="comma-separated: sensitivity,hack,invariance")
    run.add_argument("--operators", help="comma-separated operator allowlist")
    run.add_argument("--max-per-operator", type=int, help="sample at most N mutants per operator per task")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--gold-runs", type=int, default=2, help="times to run the gold solution (flakiness check)")
    run.add_argument("-j", "--jobs", type=int, default=4)
    run.add_argument("--out", type=Path, help="directory for report.md and results.json")
    run.add_argument("--min-sensitivity", type=_rate, help="fail if sensitivity is below this rate")
    run.add_argument("--min-hack-resistance", type=_rate, help="fail if hack resistance is below this rate")
    run.add_argument("--min-invariance", type=_rate, help="fail if invariance is below this rate")
    run.add_argument("-q", "--quiet", action="store_true")

    ls = sub.add_parser("list", help="list the mutants that would be generated")
    ls.add_argument("paths", nargs="+", type=Path)
    ls.add_argument("--families", type=_families, default=FAMILIES)
    return p


def cmd_list(args: argparse.Namespace) -> int:
    for task in discover_tasks(args.paths):
        gold = Snapshot.read(task.solution)
        for m in generate_all(task, gold, families=args.families):
            print(f"{task.name}\t{m.family}\t{m.id}\t{m.description}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    tasks = discover_tasks(args.paths)
    ops = {x.strip() for x in args.operators.split(",")} if args.operators else None
    say = (lambda s: None) if args.quiet else (lambda s: print(f"goodhart: {s}", file=sys.stderr, flush=True))
    results = []
    for task in tasks:
        gold = Snapshot.read(task.solution)
        unsolved = unsolved_snapshot(task, gold)
        mutants = generate_all(task, gold, args.families, ops, args.max_per_operator, args.seed, unsolved)
        for v in task.verifiers:
            if args.verifier and v.name not in args.verifier:
                continue
            results.append(run_verifier(task, v, gold, unsolved, mutants, args.gold_runs, args.jobs, say))
    if not results:
        print("goodhart: no verifiers matched", file=sys.stderr)
        return EXIT_USAGE

    md = render_markdown(results)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(md, encoding="utf-8")
        (args.out / "results.json").write_text(json.dumps(summary_json(results), indent=2), encoding="utf-8")
        say(f"wrote {args.out / 'report.md'} and {args.out / 'results.json'}")
    if not args.quiet:
        print(md.split("\n## ", 1)[0].rstrip())

    code = EXIT_OK
    floors = {"sensitivity": args.min_sensitivity, "hack": args.min_hack_resistance, "invariance": args.min_invariance}
    for vr in results:
        if status(vr) in ("gold-fails", "gold-flaky"):
            return EXIT_INVALID_TASK
        if status(vr) == "vacuous":
            code = EXIT_BELOW_THRESHOLD
        for fam, s in scores(vr).items():
            floor = floors[fam]
            if floor is not None and s.rate is not None and s.rate < floor:
                print(f"goodhart: {vr.task}/{vr.verifier} {fam} {s.rate:.2f} < {floor:.2f}", file=sys.stderr)
                code = EXIT_BELOW_THRESHOLD
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return cmd_run(args) if args.cmd == "run" else cmd_list(args)
    except TaskError as e:
        print(f"goodhart: {e}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
