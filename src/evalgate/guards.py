"""Leakage guards. They run before scoring, on the dataset itself.

* self_retrieval   the context contains the case's own source document, by id or as a
                   near copy (n-gram containment of the expected text in a context doc)
* answer_bearing   the expected answer, or its operative line, appears in the input or
                   context (verbatim after normalization, or by n-gram containment)
* whole_text_trap  not a leak in the data but in the measurement: where a whole-text
                   categorizer and the operative line disagree. Reported, never excluded.

Guards look only at what is in each case. They never read `metadata`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from evalgate.config import GuardConfig
from evalgate.normalize import collapse_whitespace, containment, normalize_text
from evalgate.operative import (
    OPERATIVE_MARKER,
    extract_operative_line,
    operative_verdict,
    whole_text_verdict,
)
from evalgate.schema import Case

SELF_RETRIEVAL = "self_retrieval"
ANSWER_BEARING = "answer_bearing"
LEAK_GUARDS = (SELF_RETRIEVAL, ANSWER_BEARING)


@dataclass(frozen=True)
class Finding:
    case_id: str
    guard: str
    detail: str
    doc_id: str | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"case_id": self.case_id, "guard": self.guard, "detail": self.detail}
        if self.doc_id is not None:
            out["doc_id"] = self.doc_id
        if self.score is not None:
            out["score"] = round(self.score, 4)
        return out


def _enabled(opts: Mapping[str, Any]) -> bool:
    return bool(opts.get("enabled", True))


def check_self_retrieval(
    case: Case, *, containment_min: float = 0.8, ngram: int = 5
) -> list[Finding]:
    findings: list[Finding] = []
    if case.source_doc_id is not None:
        for doc in case.context:
            if doc.doc_id == case.source_doc_id:
                findings.append(
                    Finding(
                        case.id,
                        SELF_RETRIEVAL,
                        "context contains the case's own source document",
                        doc_id=doc.doc_id,
                        score=1.0,
                    )
                )
    flagged = {f.doc_id for f in findings}
    expected = normalize_text(case.expected)
    for doc in case.context:
        if doc.doc_id in flagged:
            continue
        c = containment(expected, normalize_text(doc.text), ngram)
        if c >= containment_min:
            findings.append(
                Finding(
                    case.id,
                    SELF_RETRIEVAL,
                    f"context document is a near copy of the expected judgment "
                    f"({c:.0%} of its {ngram}-grams)",
                    doc_id=doc.doc_id,
                    score=c,
                )
            )
    return findings


def check_answer_bearing(case: Case, *, threshold: float = 0.7, ngram: int = 3) -> list[Finding]:
    expected = normalize_text(case.expected)
    op = extract_operative_line(case.expected)
    # Compare the ruling itself, not the marker: "the court rules" vs "the court ruled
    # that" should not decide whether a press summary restates the outcome.
    op_norm = (
        collapse_whitespace(OPERATIVE_MARKER.sub(" ", normalize_text(op.text))) if op else None
    )
    sources = [("input", None, case.input)] + [
        ("context", doc.doc_id, doc.text) for doc in case.context
    ]
    findings: list[Finding] = []
    for where, doc_id, text in sources:
        hay = normalize_text(text)
        if expected and expected in hay:
            findings.append(
                Finding(
                    case.id,
                    ANSWER_BEARING,
                    f"expected answer appears verbatim in {where}",
                    doc_id=doc_id,
                    score=1.0,
                )
            )
            continue
        if op_norm:
            if op_norm in hay:
                findings.append(
                    Finding(
                        case.id,
                        ANSWER_BEARING,
                        f"operative line appears verbatim in {where}",
                        doc_id=doc_id,
                        score=1.0,
                    )
                )
                continue
            c = containment(op_norm, hay, ngram)
            if c >= threshold:
                findings.append(
                    Finding(
                        case.id,
                        ANSWER_BEARING,
                        f"{where} restates the operative line ({c:.0%} of its {ngram}-grams)",
                        doc_id=doc_id,
                        score=c,
                    )
                )
    return findings


@dataclass
class TrapReport:
    """Where the whole-text categorizer and the operative line disagree."""

    dataset_disagreements: list[dict[str, Any]] = field(default_factory=list)
    output_disagreements: list[dict[str, Any]] = field(default_factory=list)
    n_scored: int = 0
    naive_correct: int = 0
    operative_correct: int = 0

    @property
    def naive_accuracy(self) -> float:
        return self.naive_correct / self.n_scored if self.n_scored else 0.0

    @property
    def operative_accuracy(self) -> float:
        return self.operative_correct / self.n_scored if self.n_scored else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_disagreements": self.dataset_disagreements,
            "output_disagreements": self.output_disagreements,
            "n_scored": self.n_scored,
            "naive_accuracy": round(self.naive_accuracy, 6),
            "operative_accuracy": round(self.operative_accuracy, 6),
        }


def whole_text_trap(cases: Iterable[Case], outputs: Mapping[str, str] | None = None) -> TrapReport:
    report = TrapReport()
    for case in cases:
        gold, _ = operative_verdict(case.expected)
        naive_gold = whole_text_verdict(case.expected)
        if gold is not None and naive_gold != gold:
            report.dataset_disagreements.append(
                {"case_id": case.id, "operative": gold, "whole_text": naive_gold}
            )
        if outputs is None or case.id not in outputs or gold is None:
            continue
        out = outputs[case.id]
        op, _ = operative_verdict(out)
        naive = whole_text_verdict(out)
        report.n_scored += 1
        report.operative_correct += op == gold
        report.naive_correct += naive == gold
        if op != naive:
            report.output_disagreements.append(
                {"case_id": case.id, "gold": gold, "operative": op, "whole_text": naive}
            )
    return report


@dataclass
class GuardReport:
    mode: str
    n_cases: int
    findings: list[Finding]
    trap: TrapReport | None = None

    @property
    def flagged_ids(self) -> list[str]:
        return sorted({f.case_id for f in self.findings if f.guard in LEAK_GUARDS})

    def counts(self) -> dict[str, int]:
        out = {g: 0 for g in LEAK_GUARDS}
        for g in LEAK_GUARDS:
            out[g] = len({f.case_id for f in self.findings if f.guard == g})
        return out

    @property
    def leaky(self) -> bool:
        return bool(self.flagged_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "n_cases": self.n_cases,
            "flagged": self.flagged_ids,
            "counts": self.counts(),
            "findings": [f.to_dict() for f in self.findings],
            "whole_text_trap": self.trap.to_dict() if self.trap else None,
        }


def run_guards(
    cases: Iterable[Case],
    config: GuardConfig,
    outputs: Mapping[str, str] | None = None,
) -> GuardReport:
    cases = list(cases)
    sr, ab = config.self_retrieval, config.answer_bearing
    findings: list[Finding] = []
    for case in cases:
        if _enabled(sr):
            findings += check_self_retrieval(
                case,
                containment_min=float(sr.get("containment", 0.8)),
                ngram=int(sr.get("ngram", 5)),
            )
        if _enabled(ab):
            findings += check_answer_bearing(
                case, threshold=float(ab.get("threshold", 0.7)), ngram=int(ab.get("ngram", 3))
            )
    trap = whole_text_trap(cases, outputs) if _enabled(config.whole_text_trap) else None
    return GuardReport(mode=config.mode, n_cases=len(cases), findings=findings, trap=trap)
