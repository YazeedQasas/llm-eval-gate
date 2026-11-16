import json

import pytest

from evalgate.schema import Case, ContextDoc, SchemaError, parse_case, parse_jsonl, read_cases

VALID = {
    "id": "civ-0001",
    "input": "The claimant seeks rescission of a lease.",
    "expected": "The court rules: the claim is accepted.",
    "context": [{"doc_id": "cass-114", "text": "A lease may be rescinded where ..."}],
    "tags": ["english", "civil"],
    "source_doc_id": "judg-civ-0001",
    "metadata": {"court": "first instance"},
}


def jl(*records) -> list[str]:
    return [json.dumps(r, ensure_ascii=False) + "\n" for r in records]


def test_parses_full_case():
    case = parse_case(VALID)
    assert case.id == "civ-0001"
    assert case.context == (ContextDoc("cass-114", "A lease may be rescinded where ..."),)
    assert case.tags == ("english", "civil")
    assert case.source_doc_id == "judg-civ-0001"
    assert case.metadata == {"court": "first instance"}


def test_minimal_case_defaults():
    case = parse_case({"id": "a", "input": "q", "expected": "x"})
    assert case.context == () and case.tags == () and case.source_doc_id is None


def test_roundtrip_to_dict():
    assert parse_case(VALID).to_dict() == VALID


def test_arabic_text_survives():
    case = parse_case({"id": "ar-1", "input": "حكمت المحكمة", "expected": "رد الدعوى"})
    assert case.expected == "رد الدعوى"


def test_model_view_hides_expected():
    view = parse_case(VALID).model_view()
    assert "expected" not in view
    assert "tags" not in view and "metadata" not in view
    assert view["context"][0]["doc_id"] == "cass-114"


def test_tags_deduplicated_in_order():
    case = parse_case({"id": "a", "input": "q", "expected": "x", "tags": ["b", "a", "b"]})
    assert case.tags == ("b", "a")


@pytest.mark.parametrize("field", ["id", "input", "expected"])
def test_missing_required_field(field):
    record = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(SchemaError, match=f"missing required field '{field}'"):
        parse_case(record)


@pytest.mark.parametrize("field", ["id", "input", "expected"])
def test_blank_required_field(field):
    with pytest.raises(SchemaError, match="must not be empty"):
        parse_case({**VALID, field: "   "})


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"id": 7}, "must be a string"),
        ({"expcted": "typo"}, "unknown field"),
        ({"context": "not a list"}, "'context' must be a list"),
        ({"context": [{"doc_id": "", "text": "t"}]}, "doc_id must be a non-empty string"),
        ({"context": [{"doc_id": "d", "text": 3}]}, "text must be a string"),
        ({"context": [{"doc_id": "d", "text": "t", "score": 1}]}, "unknown field"),
        (
            {"context": [{"doc_id": "d", "text": "a"}, {"doc_id": "d", "text": "b"}]},
            "appears twice",
        ),
        ({"tags": "civil"}, "list of non-empty strings"),
        ({"tags": ["ok", ""]}, "list of non-empty strings"),
        ({"source_doc_id": ""}, "source_doc_id"),
        ({"metadata": []}, "'metadata' must be an object"),
    ],
)
def test_invalid_fields(patch, message):
    with pytest.raises(SchemaError, match=message):
        parse_case({**VALID, **patch})


def test_non_object_record():
    with pytest.raises(SchemaError, match="must be a JSON object"):
        parse_case(["not", "an", "object"])


def test_jsonl_skips_blank_lines():
    lines = jl({"id": "a", "input": "q", "expected": "x"}) + ["\n", "  \n"]
    lines += jl({"id": "b", "input": "q", "expected": "y"})
    assert [c.id for c in parse_jsonl(lines)] == ["a", "b"]


def test_duplicate_ids_report_both_lines():
    lines = jl(
        {"id": "a", "input": "q", "expected": "x"},
        {"id": "b", "input": "q", "expected": "x"},
        {"id": "a", "input": "q", "expected": "y"},
    )
    with pytest.raises(SchemaError) as info:
        parse_jsonl(lines)
    assert info.value.line == 3
    assert "line 3" in str(info.value) and "first used on line 1" in str(info.value)


def test_error_carries_line_and_case_id():
    lines = jl({"id": "a", "input": "q", "expected": "x"}, {"id": "b", "input": "q"})
    with pytest.raises(SchemaError) as info:
        parse_jsonl(lines)
    assert info.value.line == 2 and info.value.case_id == "b"
    assert str(info.value).startswith("line 2, case 'b':")


def test_invalid_json_line():
    with pytest.raises(SchemaError, match="line 1: invalid JSON"):
        parse_jsonl(["{not json}\n"])


def test_read_cases_from_file(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text("".join(jl(VALID)), encoding="utf-8")
    assert read_cases(path) == [parse_case(VALID)]


def test_read_cases_tolerates_bom(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text("".join(jl(VALID)), encoding="utf-8-sig")
    assert read_cases(path)[0].id == "civ-0001"


def test_read_cases_error_names_file_once(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "a", "input": "q"}\n', encoding="utf-8")
    with pytest.raises(SchemaError) as info:
        read_cases(path)
    msg = str(info.value)
    assert msg.startswith(str(path)) and msg.count("line 1") == 1
    assert info.value.line == 1


def test_case_is_hashable_and_frozen():
    case = Case(id="a", input="q", expected="x")
    with pytest.raises(AttributeError):
        case.id = "b"  # type: ignore[misc]
