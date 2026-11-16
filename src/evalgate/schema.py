"""Golden case schema and validation.

A golden dataset is a JSONL file with one case per line. See docs/schema.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KNOWN_FIELDS = {"id", "input", "expected", "context", "tags", "source_doc_id", "metadata"}
CONTEXT_FIELDS = {"doc_id", "text"}


class SchemaError(ValueError):
    """A case (or a whole dataset) does not match the schema."""

    def __init__(self, message: str, *, line: int | None = None, case_id: str | None = None):
        self.line = line
        self.case_id = case_id
        where = []
        if line is not None:
            where.append(f"line {line}")
        if case_id is not None:
            where.append(f"case {case_id!r}")
        prefix = f"{', '.join(where)}: " if where else ""
        super().__init__(prefix + message)


@dataclass(frozen=True)
class ContextDoc:
    """One retrieved or supplied document shown to the system under test."""

    doc_id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "text": self.text}


@dataclass(frozen=True)
class Case:
    """One golden case.

    `source_doc_id` names the document the expected answer was taken from. If that
    document shows up in `context`, the model is reading the answer, not predicting it
    (the self-retrieval leak).
    """

    id: str
    input: str
    expected: str
    context: tuple[ContextDoc, ...] = ()
    tags: tuple[str, ...] = ()
    source_doc_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "input": self.input, "expected": self.expected}
        if self.context:
            out["context"] = [doc.to_dict() for doc in self.context]
        if self.tags:
            out["tags"] = list(self.tags)
        if self.source_doc_id is not None:
            out["source_doc_id"] = self.source_doc_id
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    def model_view(self) -> dict[str, Any]:
        """What the system under test is allowed to see: never `expected`.

        Cache keys are built from this, so editing an expected answer does not
        invalidate recorded outputs.
        """
        return {
            "id": self.id,
            "input": self.input,
            "context": [doc.to_dict() for doc in self.context],
        }


def _require_str(record: dict[str, Any], name: str, *, allow_empty: bool, line, case_id) -> str:
    if name not in record:
        raise SchemaError(f"missing required field {name!r}", line=line, case_id=case_id)
    value = record[name]
    if not isinstance(value, str):
        raise SchemaError(
            f"field {name!r} must be a string, got {type(value).__name__}",
            line=line,
            case_id=case_id,
        )
    if not allow_empty and not value.strip():
        raise SchemaError(f"field {name!r} must not be empty", line=line, case_id=case_id)
    return value


def parse_case(record: Any, *, line: int | None = None) -> Case:
    """Validate one decoded JSON record and turn it into a Case."""
    if not isinstance(record, dict):
        raise SchemaError(f"a case must be a JSON object, got {type(record).__name__}", line=line)

    raw_id = record.get("id")
    case_id = raw_id if isinstance(raw_id, str) else None

    unknown = set(record) - KNOWN_FIELDS
    if unknown:
        raise SchemaError(
            f"unknown field(s) {sorted(unknown)}; put extra data under 'metadata'",
            line=line,
            case_id=case_id,
        )

    cid = _require_str(record, "id", allow_empty=False, line=line, case_id=case_id)
    text_in = _require_str(record, "input", allow_empty=False, line=line, case_id=cid)
    expected = _require_str(record, "expected", allow_empty=False, line=line, case_id=cid)

    context_raw = record.get("context", [])
    if not isinstance(context_raw, list):
        raise SchemaError("field 'context' must be a list", line=line, case_id=cid)
    context: list[ContextDoc] = []
    seen_docs: set[str] = set()
    for i, doc in enumerate(context_raw):
        if not isinstance(doc, dict):
            raise SchemaError(f"context[{i}] must be an object", line=line, case_id=cid)
        extra = set(doc) - CONTEXT_FIELDS
        if extra:
            raise SchemaError(
                f"context[{i}] has unknown field(s) {sorted(extra)}", line=line, case_id=cid
            )
        doc_id = doc.get("doc_id")
        text = doc.get("text")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise SchemaError(
                f"context[{i}].doc_id must be a non-empty string", line=line, case_id=cid
            )
        if not isinstance(text, str):
            raise SchemaError(f"context[{i}].text must be a string", line=line, case_id=cid)
        if doc_id in seen_docs:
            raise SchemaError(
                f"context[{i}].doc_id {doc_id!r} appears twice", line=line, case_id=cid
            )
        seen_docs.add(doc_id)
        context.append(ContextDoc(doc_id=doc_id, text=text))

    tags_raw = record.get("tags", [])
    if not isinstance(tags_raw, list) or not all(
        isinstance(t, str) and t.strip() for t in tags_raw
    ):
        raise SchemaError(
            "field 'tags' must be a list of non-empty strings", line=line, case_id=cid
        )

    source_doc_id = record.get("source_doc_id")
    if source_doc_id is not None and (not isinstance(source_doc_id, str) or not source_doc_id):
        raise SchemaError(
            "field 'source_doc_id' must be a non-empty string", line=line, case_id=cid
        )

    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SchemaError("field 'metadata' must be an object", line=line, case_id=cid)

    return Case(
        id=cid,
        input=text_in,
        expected=expected,
        context=tuple(context),
        tags=tuple(dict.fromkeys(tags_raw)),
        source_doc_id=source_doc_id,
        metadata=metadata,
    )


def validate_cases(cases: Iterable[Case]) -> list[Case]:
    """Dataset-level checks (currently: unique ids). Returns the cases as a list."""
    out: list[Case] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise SchemaError("duplicate case id", case_id=case.id)
        seen.add(case.id)
        out.append(case)
    return out


def _iter_numbered(lines: Iterable[str]) -> Iterator[tuple[int, Case]]:
    for lineno, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"invalid JSON ({exc.msg})", line=lineno) from exc
        yield lineno, parse_case(record, line=lineno)


def parse_jsonl(lines: Iterable[str]) -> list[Case]:
    """Parse and fully validate JSONL text. Blank lines are skipped; lines are 1-based."""
    out: list[Case] = []
    first_seen: dict[str, int] = {}
    for lineno, case in _iter_numbered(lines):
        if case.id in first_seen:
            raise SchemaError(
                f"duplicate case id (first used on line {first_seen[case.id]})",
                line=lineno,
                case_id=case.id,
            )
        first_seen[case.id] = lineno
        out.append(case)
    return out


def read_cases(path: str | Path) -> list[Case]:
    """Read and fully validate a golden JSONL file."""
    p = Path(path)
    with p.open(encoding="utf-8-sig") as fh:
        try:
            return parse_jsonl(fh)
        except SchemaError as exc:
            wrapped = SchemaError(f"{p}: {exc}")
            wrapped.line, wrapped.case_id = exc.line, exc.case_id
            raise wrapped from exc
