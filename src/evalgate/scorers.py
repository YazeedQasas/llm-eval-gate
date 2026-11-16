"""Deterministic scorers.

A scorer is a pure function of (case, output): no randomness, no clock, no network,
no model. Each has a `name` and a `version`; bump the version whenever its behaviour
changes, which makes old baselines incomparable (see `scorers_fingerprint`).

Add your own with `@register`:

    @register
    class MyScorer:
        name = "my_scorer"
        version = "1"
        def __init__(self, **options): ...
        def score(self, case, output) -> ScoreResult: ...
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from evalgate.config import ConfigError, ScorerSpec
from evalgate.hashing import content_hash
from evalgate.normalize import normalize_text
from evalgate.operative import operative_verdict, whole_text_verdict
from evalgate.schema import Case


@dataclass(frozen=True)
class ScoreResult:
    score: float  # 0.0 .. 1.0
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 6), "passed": self.passed, "reason": self.reason}


@runtime_checkable
class Scorer(Protocol):
    name: str
    version: str

    def score(self, case: Case, output: str) -> ScoreResult: ...


REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    if cls.name in REGISTRY:
        raise ValueError(f"scorer {cls.name!r} is already registered")
    REGISTRY[cls.name] = cls
    return cls


def build_scorer(spec: ScorerSpec) -> Scorer:
    cls = REGISTRY.get(spec.name)
    if cls is None:
        raise ConfigError(f"unknown scorer {spec.name!r}; known: {sorted(REGISTRY)}")
    try:
        return cls(**spec.options)
    except TypeError as exc:
        raise ConfigError(f"bad options for scorer {spec.name!r}: {exc}") from exc


def build_scorers(specs: Iterable[ScorerSpec]) -> list[Scorer]:
    return [build_scorer(s) for s in specs]


def scorers_fingerprint(specs: Iterable[ScorerSpec]) -> str:
    """Hash of scorer names, versions and options. Part of every results file."""
    items = []
    for spec in specs:
        cls = REGISTRY.get(spec.name)
        items.append(
            {
                "name": spec.name,
                "version": getattr(cls, "version", "?"),
                "options": dict(spec.options),
            }
        )
    return content_hash(items)


# --------------------------------------------------------------------------- scorers


def _bool(passed: bool, reason: str) -> ScoreResult:
    return ScoreResult(1.0 if passed else 0.0, passed, reason)


@register
class ExactMatch:
    """Byte-for-byte equal after stripping surrounding whitespace."""

    name = "exact_match"
    version = "1"

    def __init__(self, strip: bool = True):
        self.strip = strip

    def score(self, case: Case, output: str) -> ScoreResult:
        a, b = (output.strip(), case.expected.strip()) if self.strip else (output, case.expected)
        return _bool(a == b, "exact match" if a == b else "differs from expected")


@register
class NormalizedMatch:
    """Equal after normalization: whitespace, punctuation, case and Arabic folding."""

    name = "normalized_match"
    version = "1"

    def __init__(self, arabic: bool = True, casefold: bool = True, punctuation: bool = True):
        self.opts = {"arabic": arabic, "casefold": casefold, "punctuation": punctuation}

    def score(self, case: Case, output: str) -> ScoreResult:
        same = normalize_text(output, **self.opts) == normalize_text(case.expected, **self.opts)
        return _bool(same, "normalized match" if same else "differs after normalization")


@register
class RegexMatch:
    """Extract a field with a regex from both output and expected, then compare.

    `pattern` is searched in each text; `group` selects the capture group.
    """

    name = "regex_match"
    version = "1"

    def __init__(self, pattern: str, group: int | str = 1, normalize: bool = True, flags: str = ""):
        flag_bits = 0
        for ch in flags:
            flag_bits |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}[ch]
        try:
            self.regex = re.compile(pattern, flag_bits)
        except re.error as exc:
            raise ConfigError(f"regex_match: bad pattern {pattern!r}: {exc}") from exc
        self.group = group
        self.normalize = normalize

    def _extract(self, text: str) -> str | None:
        m = self.regex.search(text)
        if not m:
            return None
        value = m.group(self.group) or ""
        return normalize_text(value) if self.normalize else value.strip()

    def score(self, case: Case, output: str) -> ScoreResult:
        want = self._extract(case.expected)
        if want is None:
            return _bool(False, "pattern not found in expected (fix the dataset or pattern)")
        got = self._extract(output)
        if got is None:
            return _bool(False, "pattern not found in output")
        return _bool(got == want, f"extracted {got!r}, expected {want!r}")


@register
class LabelSetF1:
    """Multi-label: split both texts into labels and score F1 of the two sets.

    Passes when F1 >= `threshold` (1.0 = exact set match).
    """

    name = "label_set_f1"
    version = "1"

    def __init__(self, separator: str = ",", threshold: float = 1.0):
        self.separator = separator
        self.threshold = threshold

    def _labels(self, text: str) -> set[str]:
        parts = (normalize_text(p) for p in text.split(self.separator))
        return {p for p in parts if p}

    def score(self, case: Case, output: str) -> ScoreResult:
        want, got = self._labels(case.expected), self._labels(output)
        if not want and not got:
            return ScoreResult(1.0, True, "both empty")
        tp = len(want & got)
        precision = tp / len(got) if got else 0.0
        recall = tp / len(want) if want else 0.0
        f1 = 0.0 if tp == 0 else 2 * precision * recall / (precision + recall)
        missing, extra = sorted(want - got), sorted(got - want)
        reason = f"f1={f1:.3f}; missing={missing}; extra={extra}"
        return ScoreResult(f1, f1 >= self.threshold, reason)


@register
class OperativeVerdict:
    """Compare the verdict of the operative line only (the fix for the whole-text trap).

    No operative line in the output is a failure, never a pass.
    """

    name = "operative_verdict"
    version = "1"

    def score(self, case: Case, output: str) -> ScoreResult:
        want, want_line = operative_verdict(case.expected)
        if want is None:
            where = "no operative line" if want_line is None else "no verdict in operative line"
            return _bool(False, f"expected has {where} (fix the dataset)")
        got, line = operative_verdict(output)
        if line is None:
            return _bool(False, "no operative line in output")
        if got is None:
            return _bool(False, f"operative line states no verdict: {line.text!r}")
        if got == want:
            return _bool(True, f"{got}: {line.text}")
        return _bool(False, f"got {got}, expected {want}: {line.text}")


@register
class WholeTextVerdict:
    """The naive whole-text categorizer. For comparison only: it falls for the trap.

    The gate refuses it as the primary scorer unless explicitly allowed.
    """

    name = "whole_text_verdict"
    version = "1"
    naive = True

    def score(self, case: Case, output: str) -> ScoreResult:
        want = whole_text_verdict(case.expected)
        got = whole_text_verdict(output)
        if got is None:
            return _bool(False, "no verdict keyword in output")
        return _bool(got == want, f"whole-text says {got}, expected (whole-text) {want}")


# --------------------------------------------------------------------------- scoring


def score_outputs(
    cases: Iterable[Case], outputs: Mapping[str, str], scorers: Iterable[Scorer]
) -> dict[str, dict[str, ScoreResult]]:
    """{case_id: {scorer_name: ScoreResult}}. A missing output fails every scorer."""
    scorers = list(scorers)
    results: dict[str, dict[str, ScoreResult]] = {}
    for case in cases:
        output = outputs.get(case.id)
        if output is None:
            results[case.id] = {s.name: _bool(False, "no output") for s in scorers}
        else:
            results[case.id] = {s.name: s.score(case, output) for s in scorers}
    return results


def _summary(values: list[ScoreResult]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "pass_rate": 0.0, "passed": 0}
    passed = sum(r.passed for r in values)
    return {
        "n": n,
        "mean": round(sum(r.score for r in values) / n, 6),
        "pass_rate": round(passed / n, 6),
        "passed": passed,
    }


def aggregate(
    cases: Iterable[Case], results: Mapping[str, Mapping[str, ScoreResult]]
) -> dict[str, dict[str, Any]]:
    """Per scorer: overall n/mean/pass_rate and the same per tag."""
    cases = [c for c in cases if c.id in results]
    names: list[str] = []
    for per_case in results.values():
        names = list(per_case)
        break
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        overall = [results[c.id][name] for c in cases]
        tags: dict[str, list[ScoreResult]] = {}
        for c in cases:
            for t in c.tags:
                tags.setdefault(t, []).append(results[c.id][name])
        out[name] = {
            **_summary(overall),
            "tags": {t: _summary(v) for t, v in sorted(tags.items())},
        }
    return out
