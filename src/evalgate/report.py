"""Markdown reports for the terminal, PR comments and GitHub job summaries."""

from __future__ import annotations

from typing import Any

from evalgate.compare import Comparison
from evalgate.guards import GuardReport

MAX_ROWS = 25


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _signed(x: float) -> str:
    return f"{x:+.1%}"


def _cell(text: str | None, limit: int = 140) -> str:
    if not text:
        return "_none_"
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def guard_section(report: GuardReport, *, heading: str = "##") -> list[str]:
    counts = report.counts()
    flagged = report.flagged_ids
    action = {
        "fail": "the run fails",
        "exclude": "flagged cases are excluded from scoring",
        "warn": "flagged cases are still scored",
    }[report.mode]
    out = [
        f"{heading} Leakage guards",
        "",
        f"Mode **{report.mode}**: {action}. {len(flagged)} of {report.n_cases} case(s) flagged.",
        "",
        "| Guard | Cases flagged |",
        "|---|---|",
        f"| self-retrieval | {counts['self_retrieval']} |",
        f"| answer-bearing context | {counts['answer_bearing']} |",
        "",
    ]
    if report.findings:
        out += [
            "<details><summary>Findings</summary>",
            "",
            "| Case | Guard | Doc | Detail |",
            "|---|---|---|---|",
        ]
        for f in report.findings[: MAX_ROWS * 2]:
            out.append(f"| `{f.case_id}` | {f.guard} | `{f.doc_id or '-'}` | {_cell(f.detail)} |")
        out += ["", "</details>", ""]
    trap = report.trap
    if trap is not None:
        out += [f"{heading} Whole-text categorizer trap", ""]
        out.append(
            f"{len(trap.dataset_disagreements)} golden answer(s) would be mislabelled by a "
            "whole-text categorizer (reasoning mentions other outcomes)."
        )
        if trap.n_scored:
            out.append(
                f"On these outputs: operative-line accuracy **{_pct(trap.operative_accuracy)}**, "
                f"whole-text accuracy {_pct(trap.naive_accuracy)} "
                f"({len(trap.output_disagreements)} disagreement(s))."
            )
        out.append("")
    return out


def summary_section(results: dict[str, Any], *, heading: str = "##") -> list[str]:
    out = [f"{heading} Scores", "", "| Scorer | Pass rate | Mean | n |", "|---|---|---|---|"]
    for name, agg in results["aggregates"].items():
        mark = " (primary)" if name == results["primary"] else ""
        out.append(f"| {name}{mark} | {_pct(agg['pass_rate'])} | {agg['mean']:.3f} | {agg['n']} |")
    out.append("")
    return out


def check_report(comp: Comparison, current: dict[str, Any], report: GuardReport) -> str:
    status = "PASS" if comp.passed else "FAIL"
    icon = "✅" if comp.passed else "❌"
    o = comp.overall
    lines = [
        f"# {icon} evalgate: {status}",
        "",
        f"Prompt `{comp.base_prompt}` (baseline) → `{comp.cur_prompt}` (this change). "
        f"Primary scorer: `{comp.primary}`.",
        "",
        "| | Baseline | This change | Δ | Regressed | Fixed | p (paired) |",
        "|---|---|---|---|---|---|---|",
        f"| **{comp.primary}** | {_pct(o.base_rate)} | {_pct(o.cur_rate)} | "
        f"{_signed(o.delta)} | {o.regressed} | {o.fixed} | {o.p_value:.4f} |",
        "",
    ]
    if comp.failures:
        lines += ["## Why the gate failed", ""] + [f"- {f}" for f in comp.failures] + [""]
    else:
        lines += ["No threshold was crossed.", ""]

    if comp.regressed:
        lines += [
            f"## Regressed cases ({len(comp.regressed)})",
            "",
            "| Case | Tags | Now | Operative line in output |",
            "|---|---|---|---|",
        ]
        for f in comp.regressed[:MAX_ROWS]:
            lines.append(
                f"| `{f.case_id}` | {', '.join(f.tags)} | {_cell(f.cur_reason.split(':')[0])} | "
                f"{_cell(f.cur_operative_line)} |"
            )
        if len(comp.regressed) > MAX_ROWS:
            lines.append(f"| … | | | {len(comp.regressed) - MAX_ROWS} more |")
        lines.append("")
    if comp.fixed:
        lines += [f"## Fixed cases ({len(comp.fixed)})", ""]
        lines += [f"- `{f.case_id}`" for f in comp.fixed[:MAX_ROWS]] + [""]

    lines += [
        "## Per tag",
        "",
        "| Tag | n | Baseline | This change | Δ | p |",
        "|---|---|---|---|---|---|",
    ]
    for t in comp.tags:
        lines.append(
            f"| {t.name} | {t.n} | {_pct(t.base_rate)} | {_pct(t.cur_rate)} | "
            f"{_signed(t.delta)} | {t.p_value:.4f} |"
        )
    lines.append("")
    lines += summary_section(current)
    lines += guard_section(report)
    return "\n".join(lines).rstrip() + "\n"


def guard_report_md(report: GuardReport) -> str:
    return "\n".join(["# evalgate guard", ""] + guard_section(report)).rstrip() + "\n"
