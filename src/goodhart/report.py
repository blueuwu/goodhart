"""Scores and Markdown rendering."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .mutants import HACK, INVARIANCE, SENSITIVITY
from .runner import MutantResult, VerifierResult

FAMILY_LABEL = {
    SENSITIVITY: ("Sensitivity", "broken solutions rejected"),
    HACK: ("Hack resistance", "reward hacks rejected"),
    INVARIANCE: ("Invariance", "equivalent rewrites accepted"),
}
FAILURE_TITLE = {
    SENSITIVITY: "Surviving mutants (accepted although behaviour changed; some may be equivalent)",
    HACK: "Hacks that earned reward",
    INVARIANCE: "False rejections (equivalent rewrite rejected)",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class Score:
    good: int
    total: int

    @property
    def rate(self) -> float | None:
        return self.good / self.total if self.total else None

    def cell(self) -> str:
        if not self.total:
            return "n/a"
        return f"{self.good}/{self.total} ({100 * self.good / self.total:.0f}%)"

    def to_json(self) -> dict:
        lo, hi = wilson(self.good, self.total)
        return {"good": self.good, "total": self.total, "rate": self.rate, "wilson95": [lo, hi]}


def scores(vr: VerifierResult) -> dict[str, Score]:
    out = {}
    for fam in (SENSITIVITY, HACK, INVARIANCE):
        ms = [m for m in vr.mutants if m.family == fam]
        out[fam] = Score(sum(m.sound for m in ms), len(ms))
    return out


def status(vr: VerifierResult) -> str:
    if not vr.gold_ok:
        return "gold-fails" if not vr.gold_flaky else "gold-flaky"
    if vr.baseline.passed:
        return "vacuous"
    return "ok"


def summary_json(results: list[VerifierResult]) -> dict:
    return {
        "verifiers": [
            {
                "task": vr.task,
                "verifier": vr.verifier,
                "status": status(vr),
                "scores": {fam: s.to_json() for fam, s in scores(vr).items()},
                **vr.to_json(),
            }
            for vr in results
        ]
    }


def _outcome(m: MutantResult) -> str:
    r = m.run
    if r.timed_out:
        return "timeout"
    if r.error and r.exit_code is None:
        return "error"
    return f"reward {r.reward:g} (exit {r.exit_code})"


def render_markdown(results: list[VerifierResult], title: str = "goodhart report") -> str:
    lines = [f"# {title}", ""]
    lines += [
        "| Task | Verifier | Gold | Unsolved | Sensitivity | Hack resistance | Invariance |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for vr in results:
        sc = scores(vr)
        gold = f"{sum(r.passed for r in vr.gold_runs)}/{len(vr.gold_runs)} pass"
        base = "**passes (vacuous)**" if vr.baseline.passed else "rejected"
        lines.append(
            f"| {vr.task} | `{vr.verifier}` | {gold} | {base} | "
            f"{sc[SENSITIVITY].cell()} | {sc[HACK].cell()} | {sc[INVARIANCE].cell()} |"
        )
    lines += [
        "",
        "*Sensitivity*: semantic mutants of the gold solution the verifier rejected. "
        "*Hack resistance*: reward hacks it rejected. *Invariance*: behaviour-preserving "
        "rewrites it accepted. Higher is better for all three.",
        "",
    ]
    for vr in results:
        lines += [f"## {vr.task} / `{vr.verifier}`", ""]
        if vr.description:
            lines += [vr.description, ""]
        st = status(vr)
        if st != "ok":
            msg = {
                "gold-fails": "The gold solution does not pass this verifier, so no mutants were scored.",
                "gold-flaky": "The gold solution passed on some runs and failed on others, so no mutants were scored.",
                "vacuous": "The unsolved workspace already passes: the verifier rewards doing nothing, so hack scores are meaningless.",
            }[st]
            lines += [f"> **{st}**: {msg}", ""]
            if st != "vacuous":
                tail = vr.gold_runs[-1].output_tail if vr.gold_runs else ""
                lines += ["```text", tail.strip()[-800:], "```", ""]
                continue
        sc = scores(vr)
        for fam in (SENSITIVITY, HACK, INVARIANCE):
            label, what = FAMILY_LABEL[fam]
            lines.append(f"- **{label}**: {sc[fam].cell()} {what}")
        lines.append("")
        for fam in (HACK, INVARIANCE, SENSITIVITY):
            bad = [m for m in vr.mutants if m.family == fam and not m.sound]
            if not bad:
                continue
            lines += [f"### {FAILURE_TITLE[fam]}: {len(bad)}", ""]
            for m in bad:
                lines.append(f"<details><summary><code>{m.mutant_id}</code>: {_md_inline(m.description)} → {_outcome(m)}</summary>")
                lines += ["", "```diff", m.diff.rstrip(), "```", "", "</details>", ""]
        by_op: dict[tuple[str, str], list[MutantResult]] = {}
        for m in vr.mutants:
            by_op.setdefault((m.family, m.operator), []).append(m)
        if by_op:
            lines += ["<details><summary>Per-operator breakdown</summary>", "", "| Family | Operator | Sound | Total |", "|---|---|---:|---:|"]
            for (fam, op), ms in sorted(by_op.items()):
                lines.append(f"| {fam} | `{op}` | {sum(m.sound for m in ms)} | {len(ms)} |")
            lines += ["", "</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def _md_inline(s: str) -> str:
    return s.replace("<", "&lt;").replace(">", "&gt;").replace("`", "")
