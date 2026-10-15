"""Draw the README's hack-matrix figure (light and dark SVG) from results/examples/results.json.

    python examples/hack_matrix_svg.py
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIERS = ["naive", "hidden-exit-code", "hardened", "isolated", "canonical"]
ORDER = [
    "conftest-force-pass", "conftest-skip-all", "neuter-asserts", "memorize-visible-tests",
    "shadow-pytest", "import-exit0", "atexit-exit0", "inprocess-report-patch",
    "delete-tests", "import-skip",
]
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9",
                  paid="#d03b3b", paid_ink="#ffffff", ok="#006300", cell="#f3f2ee"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
                 paid="#d03b3b", paid_ink="#ffffff", ok="#0ca30c", cell="#232321"),
}
FONT = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def load() -> tuple[dict[str, dict[str, tuple[int, int]]], int]:
    data = json.loads((ROOT / "results/examples/results.json").read_text(encoding="utf-8"))
    counts: dict[str, dict[str, tuple[int, int]]] = {}
    tasks = {r["task"] for r in data["verifiers"]}
    for r in data["verifiers"]:
        for m in r["mutants"]:
            if m["family"] != "hack" or m["run"]["infra_error"]:
                continue
            won, n = counts.setdefault(m["operator"], {}).get(r["verifier"], (0, 0))
            counts[m["operator"]][r["verifier"]] = (won + int(m["run"]["passed"]), n + 1)
    return counts, len(tasks)


def svg(theme: dict[str, str], counts: dict[str, dict[str, tuple[int, int]]], n_tasks: int) -> str:
    label_w, col_w, row_h, gap = 236, 128, 34, 2
    top, left = 92, 24
    width = left + label_w + col_w * len(VERIFIERS) + 24
    height = top + row_h * len(ORDER) + 64
    t = theme
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">',
        '<title id="t">Which reward hacks earn full reward, by grader</title>',
        f'<desc id="d">Grid of {len(ORDER)} hacks by {len(VERIFIERS)} graders over {n_tasks} example tasks. '
        "Cells marked paid show how many tasks the hack earned full reward on.</desc>",
        f'<rect width="{width}" height="{height}" rx="12" fill="{t["surface"]}"/>',
        f'<text x="{left}" y="36" font-family="{FONT}" font-size="18" font-weight="600" fill="{t["ink"]}">'
        "Which reward hacks earn full reward</text>",
        f'<text x="{left}" y="58" font-family="{FONT}" font-size="13" fill="{t["ink2"]}">'
        f"Each hack starts from an unsolved workspace. Cells count tasks (of {n_tasks}) where the grader paid out.</text>",
    ]
    for j, v in enumerate(VERIFIERS):
        cx = left + label_w + j * col_w + col_w / 2
        out.append(f'<text x="{cx}" y="{top - 10}" text-anchor="middle" font-family="{MONO}" font-size="12.5" '
                   f'fill="{t["ink2"]}">{escape(v)}</text>')
    for i, op in enumerate(ORDER):
        y = top + i * row_h
        out.append(f'<text x="{left}" y="{y + row_h / 2 + 4.5}" font-family="{MONO}" font-size="12.5" '
                   f'fill="{t["ink"]}">{escape(op)}</text>')
        for j, v in enumerate(VERIFIERS):
            x = left + label_w + j * col_w
            won, n = counts.get(op, {}).get(v, (0, 0))
            cx, cy = x + col_w / 2, y + row_h / 2
            if won:
                out.append(f'<rect x="{x + gap}" y="{y + gap}" width="{col_w - 2 * gap}" height="{row_h - 2 * gap}" '
                           f'rx="4" fill="{t["paid"]}"/>')
                out.append(f'<text x="{cx}" y="{cy + 4.5}" text-anchor="middle" font-family="{FONT}" font-size="12.5" '
                           f'font-weight="600" fill="{t["paid_ink"]}">✕ paid {won}/{n}</text>')
            else:
                out.append(f'<rect x="{x + gap}" y="{y + gap}" width="{col_w - 2 * gap}" height="{row_h - 2 * gap}" '
                           f'rx="4" fill="{t["cell"]}"/>')
                out.append(f'<text x="{cx}" y="{cy + 4.5}" text-anchor="middle" font-family="{FONT}" font-size="12.5" '
                           f'fill="{t["muted"]}"><tspan fill="{t["ok"]}">✓</tspan> blocked</text>')
    foot = top + row_h * len(ORDER) + 28
    out.append(f'<text x="{left}" y="{foot}" font-family="{FONT}" font-size="12" fill="{t["ink2"]}">'
               "canonical blocks the in-process patch only because it rejects any change to the solution's AST, "
               "valid rewrites included.</text>")
    out.append(f'<text x="{left}" y="{foot + 18}" font-family="{FONT}" font-size="12" fill="{t["muted"]}">'
               "goodhart · examples/tasks · reproduce with: goodhart run examples/tasks</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    counts, n_tasks = load()
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (docs / f"hack-matrix-{name}.svg").write_text(svg(theme, counts, n_tasks), encoding="utf-8")
    print("wrote docs/hack-matrix-{light,dark}.svg")


if __name__ == "__main__":
    main()
