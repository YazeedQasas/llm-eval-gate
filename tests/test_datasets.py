import json
from collections import Counter

import pytest

from evalgate.datasets import dataset_hash, filter_by_tags, load_dataset
from evalgate.operative import operative_verdict, whole_text_verdict
from evalgate.schema import Case, SchemaError

from .conftest import DEMO


def write(tmp_path, records, name="d.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), "utf-8")
    return p


RECS = [
    {"id": "a", "input": "q1", "expected": "x", "tags": ["arabic"]},
    {"id": "b", "input": "q2", "expected": "y", "tags": ["english"]},
    {"id": "c", "input": "q3", "expected": "z", "tags": ["arabic", "civil"]},
]


def test_load_and_hash(tmp_path):
    ds = load_dataset(write(tmp_path, RECS))
    assert len(ds) == 3 and len(ds.hash) == 64
    assert ds.tag_counts() == {"arabic": 2, "civil": 1, "english": 1}


def test_hash_ignores_line_order(tmp_path):
    a = load_dataset(write(tmp_path, RECS, "a.jsonl"))
    b = load_dataset(write(tmp_path, list(reversed(RECS)), "b.jsonl"))
    assert a.hash == b.hash


def test_hash_changes_when_expected_changes(tmp_path):
    edited = [dict(RECS[0], expected="changed"), *RECS[1:]]
    assert (
        load_dataset(write(tmp_path, RECS, "a.jsonl")).hash
        != load_dataset(write(tmp_path, edited, "b.jsonl")).hash
    )


def test_tag_filter(tmp_path):
    ds = load_dataset(write(tmp_path, RECS), tags=["arabic"])
    assert [c.id for c in ds] == ["a", "c"]
    assert ds.tags_filter == ("arabic",)
    assert ds.hash != load_dataset(write(tmp_path, RECS, "x.jsonl")).hash


def test_filter_by_tags_empty_keeps_all():
    cases = [Case(id="a", input="q", expected="x")]
    assert filter_by_tags(cases, []) == cases


def test_errors_have_line_numbers(tmp_path):
    p = write(tmp_path, [RECS[0], {"id": "b", "input": "q"}])
    with pytest.raises(SchemaError, match="line 2"):
        load_dataset(p)


def test_dataset_hash_is_pure():
    cases = [Case(id="a", input="q", expected="x")]
    assert dataset_hash(cases) == dataset_hash(list(cases))


# --- the shipped demo set ------------------------------------------------------


def test_demo_set_shape():
    ds = load_dataset(DEMO / "cases.jsonl")
    assert 60 <= len(ds) <= 100
    langs = Counter("english" if "english" in c.tags else "arabic" for c in ds)
    assert langs["english"] == langs["arabic"]
    assert all(c.metadata.get("synthetic") for c in ds)


def test_demo_every_expected_has_one_clear_operative_line():
    for case in load_dataset(DEMO / "cases.jsonl"):
        verdict, line = operative_verdict(case.expected)
        assert line is not None, case.id
        assert verdict == case.metadata["verdict"], case.id


def test_demo_seeded_traps_present():
    traps = Counter(c.metadata.get("seeded_trap") for c in load_dataset(DEMO / "cases.jsonl"))
    assert traps["self_retrieval"] >= 6
    assert traps["answer_bearing"] >= 6
    assert traps["whole_text"] >= 6


def test_demo_whole_text_cases_fool_the_naive_categorizer():
    for case in load_dataset(DEMO / "cases.jsonl"):
        fooled = whole_text_verdict(case.expected) != case.metadata["verdict"]
        assert fooled == (case.metadata.get("seeded_trap") == "whole_text"), case.id


def test_demo_builder_is_deterministic(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_demo_dataset", DEMO.parents[1] / "scripts" / "build_demo_dataset.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "cases.jsonl"
    monkeypatch.setattr(mod, "OUT", out)
    mod.main()
    assert out.read_bytes() == (DEMO / "cases.jsonl").read_bytes()
