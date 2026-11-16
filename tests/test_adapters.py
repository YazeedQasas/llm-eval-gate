import hashlib
import json
import socket
from datetime import UTC, datetime

import pytest

from evalgate.adapters import (
    Adapter,
    CacheMiss,
    GenerationParams,
    LiveAdapter,
    NondeterministicParams,
    Recording,
    ReplayAdapter,
    ReplayCache,
    cache_key,
)
from evalgate.hashing import canonical_json, content_hash
from evalgate.schema import Case, ContextDoc

CASE = Case(
    id="civ-0001",
    input="الدعوى تتعلق بفسخ عقد إيجار",
    expected="حكمت المحكمة بقبول الدعوى",
    context=(ContextDoc("cass-114", "يجوز فسخ عقد الإيجار ..."),),
    tags=("arabic",),
)
FIXED_CLOCK = lambda: datetime(2026, 11, 16, 10, 0, tzinfo=UTC)  # noqa: E731


def key(case=CASE, **overrides):
    kwargs = dict(
        adapter="judgment-prompt",
        adapter_version="v1",
        model="model-x",
        params=GenerationParams(),
        case=case,
    )
    kwargs.update(overrides)
    return cache_key(**kwargs)


def fake_model(case: Case, params: GenerationParams) -> str:
    return f"OUTPUT for {case.id} at t={params.temperature}"


def live(cache, **kw):
    return LiveAdapter(
        name="judgment-prompt",
        version="v1",
        model="model-x",
        fn=fake_model,
        cache=cache,
        clock=FIXED_CLOCK,
        **kw,
    )


def replay(cache, **kw):
    defaults = dict(name="judgment-prompt", version="v1", model="model-x", cache=cache)
    defaults.update(kw)
    return ReplayAdapter(**defaults)


# --- hashing ---------------------------------------------------------------


def test_canonical_json_ignores_key_order_and_keeps_unicode():
    assert canonical_json({"b": 1, "a": "حكم"}) == canonical_json({"a": "حكم", "b": 1})
    assert "حكم" in canonical_json({"a": "حكم"})


def test_content_hash_is_sha256_of_canonical_form():
    # Pinned to the exact byte form so an accidental change to canonicalization is caught.
    expected = hashlib.sha256('{"a":1,"b":"حكم"}'.encode()).hexdigest()
    assert content_hash({"b": "حكم", "a": 1}) == expected


# --- cache key -------------------------------------------------------------


def test_same_inputs_same_key():
    assert key() == key()
    assert key() == key(case=Case(**{**CASE.__dict__}))


def test_key_ignores_expected_tags_and_metadata():
    edited = Case(
        id=CASE.id,
        input=CASE.input,
        expected="something else",
        context=CASE.context,
        tags=("other",),
        metadata={"note": "x"},
    )
    assert key(case=edited) == key()


@pytest.mark.parametrize(
    "override",
    [
        {"adapter": "other-prompt"},
        {"adapter_version": "v2"},
        {"model": "model-y"},
        {"params": GenerationParams(seed=1)},
        {"params": GenerationParams(max_tokens=512)},
        {"case": Case(id=CASE.id, input=CASE.input + "!", expected=CASE.expected)},
        {"case": Case(id="civ-0002", input=CASE.input, expected=CASE.expected)},
    ],
)
def test_key_changes_with_anything_the_model_sees(override):
    assert key(**override) != key()


def test_key_changes_with_context():
    no_ctx = Case(id=CASE.id, input=CASE.input, expected=CASE.expected)
    assert key(case=no_ctx) != key()


# --- live -> replay roundtrip ----------------------------------------------


def test_live_records_and_replay_serves(tmp_path):
    cache = ReplayCache()
    out = live(cache).generate(CASE)
    assert out == "OUTPUT for civ-0001 at t=0.0"
    assert len(cache) == 1

    path = tmp_path / "outputs.jsonl"
    cache.save(path)
    loaded = ReplayCache.load(path)
    assert replay(loaded).generate(CASE) == out


def test_saved_file_is_stable_and_sorted(tmp_path):
    cache = ReplayCache()
    lv = live(cache)
    for cid in ["b", "a", "c"]:
        lv.generate(Case(id=cid, input="q", expected="x"))
    p1, p2 = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    cache.save(p1)
    ReplayCache.load(p1).save(p2)
    assert p1.read_bytes() == p2.read_bytes()
    lines = p1.read_text(encoding="utf-8").splitlines()
    ids = [Recording.from_dict(json.loads(line)).case_id for line in lines]
    assert ids == ["a", "b", "c"]


def test_replay_miss_is_loud():
    with pytest.raises(CacheMiss, match="civ-0001.*judgment-prompt@v1.*re-record"):
        replay(ReplayCache()).generate(CASE)


def test_prompt_bump_invalidates_recordings():
    cache = ReplayCache()
    live(cache).generate(CASE)
    with pytest.raises(CacheMiss):
        replay(cache, version="v2").generate(CASE)


def test_replay_never_touches_network(monkeypatch):
    cache = ReplayCache()
    live(cache).generate(CASE)

    def no_network(*_a, **_k):
        raise AssertionError("network access during replay")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert replay(cache).generate(CASE).startswith("OUTPUT")


def test_replay_deterministic_over_many_calls():
    cache = ReplayCache()
    live(cache).generate(CASE)
    rp = replay(cache)
    assert len({rp.generate(CASE) for _ in range(100)}) == 1


# --- determinism guards ----------------------------------------------------


def test_live_rejects_nonzero_temperature():
    with pytest.raises(NondeterministicParams):
        live(ReplayCache(), params=GenerationParams(temperature=0.7))


def test_live_allows_override():
    adapter = live(
        ReplayCache(), params=GenerationParams(temperature=0.7), allow_nondeterministic=True
    )
    assert adapter.generate(CASE).endswith("t=0.7")


def test_conflicting_recordings_rejected():
    outputs = iter(["first", "second"])
    cache = ReplayCache()
    flaky = LiveAdapter(
        name="p", version="v1", model="m", fn=lambda c, p: next(outputs), cache=cache
    )
    flaky.generate(CASE)
    with pytest.raises(ValueError, match="conflicting outputs"):
        flaky.generate(CASE)


def test_live_rejects_non_string_output():
    adapter = LiveAdapter(
        name="p", version="v1", model="m", fn=lambda c, p: 42, cache=ReplayCache()
    )
    with pytest.raises(TypeError):
        adapter.generate(CASE)


def test_load_reports_bad_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"key": "k"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1: bad recording"):
        ReplayCache.load(path)


def test_adapters_satisfy_protocol():
    assert isinstance(replay(ReplayCache()), Adapter)
    assert isinstance(live(ReplayCache()), Adapter)
