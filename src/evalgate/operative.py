"""Operative-line extraction and verdict categories for judgment texts.

A judgment has reasoning followed by an operative part (the ruling itself). Reasoning
routinely mentions other outcomes ("the objection to jurisdiction is rejected") while
the ruling accepts the claim. A classifier that reads the whole text picks those words
up and gets the verdict wrong: the whole-text categorizer trap. The fix is to find the
operative line and categorize only that.

All matching runs on `normalize_text` output, so Arabic spelling variants and
diacritics don't matter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evalgate.normalize import normalize_text

DISMISSED = "dismissed"  # inadmissible / not heard on the merits
PARTIAL = "partial"  # accepted in part
REJECTED = "rejected"  # heard and rejected
ACCEPTED = "accepted"  # accepted in full

# Order matters: the first category whose pattern matches the operative line wins.
# "بعدم قبول" contains "قبول" and "partially accepted" contains "accepted", so the more
# specific categories are checked first.
VERDICT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        DISMISSED,
        re.compile(r"\b(?:inadmissible|not admissible)\b|(?:^|\s)ب?عدم قبول(?:\s|$)"),
    ),
    (
        PARTIAL,
        re.compile(
            r"\b(?:partially|partly) (?:accepted|granted)\b|\baccepted in part\b"
            r"|(?:^|\s)جزئيا(?:\s|$)"
        ),
    ),
    (
        REJECTED,
        re.compile(r"\b(?:rejected|dismissed|denied)\b|(?:^|\s)ب?(?:رد|رفض)(?:\s|$)"),
    ),
    (
        ACCEPTED,
        re.compile(r"\b(?:accepted|granted|upheld)\b|(?:^|\s)ب?قبول(?:\s|$)"),
    ),
)
VERDICTS = tuple(name for name, _ in VERDICT_PATTERNS)

# Markers that open the operative part. Matched on normalized text
# (so "الأسباب" is written "الاسباب" and "the court rules:" is "the court rules").
OPERATIVE_MARKER = re.compile(
    r"\bthe court (?:hereby )?(?:rules|decides|orders|holds)\b"
    r"|^ruling\b|\boperative part\b|\bfor these reasons\b"
    r"|(?:^|\s)(?:حكمت|قررت) المحكمه(?:\s|$)"
    r"|(?:^|\s)لهذه الاسباب(?:\s|$)|(?:^|\s)منطوق الحكم(?:\s|$)"
)


@dataclass(frozen=True)
class OperativeLine:
    text: str  # original text of the operative line (not normalized)
    line_no: int  # 1-based line where it starts


def categorize(text: str) -> str | None:
    """Verdict of a short text (an operative line). None if no verdict is stated."""
    norm = normalize_text(text)
    for name, pattern in VERDICT_PATTERNS:
        if pattern.search(norm):
            return name
    return None


def extract_operative_line(text: str) -> OperativeLine | None:
    """Return the last operative line in `text`, or None if there is none.

    The last marker wins: a judgment can quote an earlier ruling in its reasoning, but
    its own operative part comes at the end. If the marker line states no verdict
    ("For these reasons:"), the next non-empty line is joined to it.
    """
    lines = text.splitlines()
    found: int | None = None
    for i, line in enumerate(lines):
        if OPERATIVE_MARKER.search(normalize_text(line)):
            found = i
    if found is None:
        return None

    raw = lines[found].strip()
    # Start at the marker when it sits mid-line ("... as argued. The court rules: ...").
    start = _marker_offset(raw)
    piece = raw[start:].strip()
    if categorize(piece) is None:
        for nxt in lines[found + 1 :]:
            if nxt.strip():
                piece = f"{piece} {nxt.strip()}"
                break
    return OperativeLine(text=piece, line_no=found + 1)


def _marker_offset(line: str) -> int:
    """Character offset in the original line where the last operative marker begins.

    Normalization changes lengths, so walk sentence starts in the original text and
    keep the last one from which the marker is still present.
    """
    candidates = [0] + [m.end() for m in re.finditer(r"[.!؟?;؛]\s+", line)]
    best = 0
    for pos in candidates:
        if OPERATIVE_MARKER.search(normalize_text(line[pos:])):
            best = pos
    return best


def operative_verdict(text: str) -> tuple[str | None, OperativeLine | None]:
    """(verdict, operative line) of a judgment text, reading the operative line only."""
    line = extract_operative_line(text)
    if line is None:
        return None, None
    return categorize(line.text), line


def whole_text_verdict(text: str) -> str | None:
    """The naive categorizer: count verdict keywords across the whole text.

    Kept only to measure the trap. Never use it as a scorer.
    """
    norm = normalize_text(text)
    counts = {name: len(pattern.findall(norm)) for name, pattern in VERDICT_PATTERNS}
    best = max(counts.values())
    if best == 0:
        return None
    return next(name for name in VERDICTS if counts[name] == best)
