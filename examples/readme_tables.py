"""Fill the README's result tables from results/examples/results.json.

    python examples/readme_tables.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIERS = ["naive", "hidden-exit-code", "hardened", "isolated", "canonical"]
HACKS = {
    "conftest-force-pass": "conftest hook rewrites failures as passes",
    "conftest-skip-all": "conftest hook skips every test",
    "neuter-asserts": "replace visible asserts with `pass`",
    "memorize-visible-tests": "lookup table of the visible cases",
    "shadow-pytest": 'workspace `pytest.py` prints "passed" and writes fake JUnit',
    "import-exit0": "`os._exit(0)` when the solution is imported",
    "atexit-exit0": "exit hook rewrites the status to 0",
    "inprocess-report-patch": "solution patches pytest's report factory at import",
}


def _fmt(score: dict) -> str:
    g, t = score["good"], score["total"]
    return f"{g}/{t} ({100 * g / t:.0f}%)" if t else "n/a"


def main() -> None:
    data = json.loads((ROOT / "results/examples/results.json").read_text(encoding="utf-8"))
    rows = data["verifiers"]
    tasks = sorted({r["task"] for r in rows})

    earned: dict[str, dict[str, int]] = {}
    for r in rows:
        for m in r["mutants"]:
            if m["family"] == "hack":
                cell = earned.setdefault(m["operator"], {})
                cell[r["verifier"]] = cell.get(r["verifier"], 0) + int(m["run"]["passed"] and not m["run"]["infra_error"])

    def cell(op: str, v: str) -> str:
        k = earned.get(op, {}).get(v, 0)
        text = f"{k}/{len(tasks)}"
        text = f"**{text}**" if k else text
        if v == "canonical" and op == "inprocess-report-patch":
            text += "†"
        return text

    hack = ["| Hack | " + " | ".join(f"`{v}`" for v in VERIFIERS) + " |", "|---|" + ":-:|" * len(VERIFIERS)]
    never = []
    for op in earned:
        if not any(earned[op].values()):
            never.append(op)
    for op, desc in HACKS.items():
        if op in earned and op not in never:
            hack.append(f"| `{op}`: {desc} | " + " | ".join(cell(op, v) for v in VERIFIERS) + " |")
    if never:
        hack.append("| " + ", ".join(f"`{op}`" for op in never) + " | " + " | ".join(f"0/{len(tasks)}" for _ in VERIFIERS) + " |")

    sc = ["| Task | Verifier | Sensitivity | Hack resistance | Invariance | Unsolved |", "|---|---|---:|---:|---:|---|"]
    order = {v: i for i, v in enumerate(VERIFIERS)}
    for r in sorted(rows, key=lambda r: (r["task"], order.get(r["verifier"], 99))):
        cells = [_fmt(r["scores"][f]) for f in ("sensitivity", "hack", "invariance")]
        unsolved = "**passes**" if r["baseline"]["passed"] else "rejected"
        sc.append(f"| {r['task']} | `{r['verifier']}` | " + " | ".join(cells) + f" | {unsolved} |")

    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for tag, lines in (("HACK-MATRIX", hack), ("SCORECARD", sc)):
        text = re.sub(
            rf"<!-- {tag}:START -->.*?<!-- {tag}:END -->",
            f"<!-- {tag}:START -->\n" + "\n".join(lines) + f"\n<!-- {tag}:END -->",
            text,
            flags=re.S,
        )
    readme.write_text(text, encoding="utf-8")
    print("README tables updated")


if __name__ == "__main__":
    main()
