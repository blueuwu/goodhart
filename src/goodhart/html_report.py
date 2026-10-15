"""Self-contained HTML report: scorecard, hack matrix, and every unsound mutant's diff."""

from __future__ import annotations

import html

from .mutants import HACK, INVARIANCE, SENSITIVITY
from .report import FAILURE_TITLE, scores, status
from .runner import VerifierResult

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--card:#ffffff;
--good:#1f7a4d;--good-bg:#e5f3ea;--bad:#b3261e;--bad-bg:#fbe7e5;--warn:#8a5a00;--warn-bg:#fdf1d6;
--code:#f3f1ea;--add:#e6f4ea;--del:#fbe9e7}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141413;--fg:#ecebe6;--muted:#9c9a92;
--line:#2c2b28;--card:#1c1c1a;--good:#7fd1a4;--good-bg:#183326;--bad:#f2a199;--bad-bg:#3a1c19;
--warn:#f0c46a;--warn-bg:#3a2e12;--code:#22221f;--add:#173124;--del:#3a1d1a}}
:root[data-theme=dark]{--bg:#141413;--fg:#ecebe6;--muted:#9c9a92;--line:#2c2b28;--card:#1c1c1a;
--good:#7fd1a4;--good-bg:#183326;--bad:#f2a199;--bad-bg:#3a1c19;--warn:#f0c46a;--warn-bg:#3a2e12;
--code:#22221f;--add:#173124;--del:#3a1d1a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 16px 80px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:19px;margin:40px 0 12px}
h3{font-size:15px;margin:20px 0 8px}p.sub{color:var(--muted);margin:0 0 28px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;color:var(--muted);font-size:13px}tr:last-child td{border-bottom:0}
td.num{text-align:right}code{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:13px;font-weight:600}
.g{background:var(--good-bg);color:var(--good)}.b{background:var(--bad-bg);color:var(--bad)}
.w{background:var(--warn-bg);color:var(--warn)}.cell{text-align:center}
section.v{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:4px 18px 14px;margin:14px 0}
details{border-top:1px solid var(--line);padding:8px 0}details summary{cursor:pointer;list-style:none}
details summary::-webkit-details-marker{display:none}details summary:before{content:"\\25B8 ";color:var(--muted)}
details[open] summary:before{content:"\\25BE "}
pre{background:var(--code);border-radius:8px;padding:10px 12px;overflow-x:auto;margin:8px 0 0;font-size:12.5px;line-height:1.45}
.add{background:var(--add);display:block}.del{background:var(--del);display:block}
.muted{color:var(--muted)}.legend{color:var(--muted);font-size:13px;margin-top:8px}
"""


def _e(s: object) -> str:
    return html.escape(str(s))


def _pill(good: int, total: int) -> str:
    if not total:
        return '<span class="muted">n/a</span>'
    cls = "g" if good == total else ("w" if good / total >= 0.8 else "b")
    return f'<span class="pill {cls}">{good}/{total}</span>'


def _diff(text: str) -> str:
    out = []
    for line in text.splitlines():
        cls = "add" if line.startswith("+") and not line.startswith("+++") else (
            "del" if line.startswith("-") and not line.startswith("---") else "")
        out.append(f'<span class="{cls}">{_e(line)}</span>' if cls else _e(line))
    return "<pre>" + "\n".join(out) + "</pre>"


def render_html(results: list[VerifierResult], title: str = "goodhart report") -> str:
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
             f'<meta name=viewport content="width=device-width,initial-scale=1">'
             f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>",
             f"<h1>{_e(title)}</h1>",
             '<p class="sub">Sensitivity: broken solutions rejected. Hack resistance: reward hacks rejected '
             "(applied to the unsolved workspace). Invariance: equivalent rewrites accepted.</p>",
             '<div class="wrap"><table><tr><th>Task</th><th>Verifier</th><th>Status</th>'
             '<th class="cell">Sensitivity</th><th class="cell">Hack resistance</th><th class="cell">Invariance</th></tr>']
    for vr in results:
        sc = scores(vr)
        st = status(vr)
        st_html = '<span class="pill g">ok</span>' if st == "ok" else f'<span class="pill b">{_e(st)}</span>'
        parts.append(
            f"<tr><td>{_e(vr.task)}</td><td><code>{_e(vr.verifier)}</code></td><td>{st_html}</td>"
            + "".join(f'<td class="cell">{_pill(sc[f].good, sc[f].total)}</td>' for f in (SENSITIVITY, HACK, INVARIANCE))
            + "</tr>")
    parts.append("</table></div>")

    hacks = sorted({m.operator for vr in results for m in vr.mutants if m.family == HACK})
    verifiers = list(dict.fromkeys(vr.verifier for vr in results))
    if hacks:
        parts += ["<h2>Which hacks earned reward</h2>",
                  '<div class="wrap"><table><tr><th>Hack</th>'
                  + "".join(f'<th class="cell"><code>{_e(v)}</code></th>' for v in verifiers) + "</tr>"]
        for op in hacks:
            row = [f"<td><code>{_e(op)}</code></td>"]
            for v in verifiers:
                ms = [m for vr in results if vr.verifier == v for m in vr.mutants if m.operator == op and m.evaluated]
                won = sum(m.run.passed for m in ms)
                cls = "b" if won else "g"
                row.append(f'<td class="cell"><span class="pill {cls}">{won}/{len(ms)}</span></td>' if ms
                           else '<td class="cell muted">-</td>')
            parts.append("<tr>" + "".join(row) + "</tr>")
        parts.append('</table></div><p class="legend">Cells count tasks where the hack earned full reward. Red means the grader paid out for it.</p>')

    parts.append("<h2>Details</h2>")
    for vr in results:
        parts.append(f'<section class="v"><h3>{_e(vr.task)} / <code>{_e(vr.verifier)}</code></h3>')
        if vr.description:
            parts.append(f'<p class="muted">{_e(vr.description)}</p>')
        any_bad = False
        for fam in (HACK, INVARIANCE, SENSITIVITY):
            bad = [m for m in vr.mutants if m.family == fam and m.evaluated and not m.sound]
            if not bad:
                continue
            any_bad = True
            parts.append(f"<p><strong>{_e(FAILURE_TITLE[fam])}: {len(bad)}</strong></p>")
            for m in bad:
                parts.append(f"<details><summary><code>{_e(m.mutant_id)}</code> <span class=muted>{_e(m.description)}</span>"
                             f"</summary>{_diff(m.diff)}</details>")
        errored = [m for m in vr.mutants if not m.evaluated]
        if errored:
            parts.append(f'<p class="muted">{len(errored)} unevaluated mutant(s) excluded from scores.</p>')
        if not any_bad:
            parts.append('<p class="muted">Every mutant was handled soundly.</p>')
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)
