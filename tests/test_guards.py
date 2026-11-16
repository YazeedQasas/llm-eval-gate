import pytest

from evalgate.config import GuardConfig, load_config
from evalgate.datasets import load_dataset
from evalgate.guards import (
    ANSWER_BEARING,
    SELF_RETRIEVAL,
    check_answer_bearing,
    check_self_retrieval,
    run_guards,
    whole_text_trap,
)
from evalgate.schema import Case, ContextDoc

EXPECTED = (
    "Reasoning: the documents prove the breach and the defence has no support.\n"
    "The court rules: the claim is accepted and the defendant is ordered to pay 14,000."
)


def mk(context=(), source="judg-1", input_text="The claimant seeks unpaid rent."):
    return Case(
        id="c1",
        input=input_text,
        expected=EXPECTED,
        context=tuple(ContextDoc(d, t) for d, t in context),
        source_doc_id=source,
    )


PRINCIPLE = ("cass-1", "A landlord may seek rescission where the tenant fails to pay rent.")


def test_clean_case_not_flagged():
    c = mk([PRINCIPLE])
    assert check_self_retrieval(c) == [] and check_answer_bearing(c) == []


def test_self_retrieval_by_id():
    (f,) = check_self_retrieval(mk([PRINCIPLE, ("judg-1", "whatever text")]))
    assert f.guard == SELF_RETRIEVAL and f.doc_id == "judg-1"


def test_self_retrieval_near_copy_under_other_id():
    copy = "Archived copy. " + EXPECTED.upper().replace("14,000", "14,000.")
    (f,) = check_self_retrieval(mk([PRINCIPLE, ("archive-9", copy)]))
    assert f.doc_id == "archive-9" and f.score >= 0.8


def test_self_retrieval_threshold():
    half = " ".join(EXPECTED.split()[:12])
    c = mk([("x", half)])
    assert check_self_retrieval(c, containment_min=0.8) == []
    assert check_self_retrieval(c, containment_min=0.2) != []


def test_answer_bearing_verbatim_in_input():
    c = mk(input_text="Summary. " + EXPECTED)
    (f,) = check_answer_bearing(c)
    assert f.guard == ANSWER_BEARING and "input" in f.detail


def test_answer_bearing_press_summary_with_different_marker():
    press = (
        "Press summary: the court ruled that the claim is accepted and the defendant is "
        "ordered to pay 14,000."
    )
    (f,) = check_answer_bearing(mk([PRINCIPLE, ("news-1", press)]))
    assert f.doc_id == "news-1"


def test_answer_bearing_arabic_needs_normalization():
    exp = "الأسباب: ثبت الإخلال.\nحكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بدفع 9,000."
    press = "ملخص: حَكَمَت المحكمةُ بقبولِ الدعوى وإلزام المدعى عليه بدفع 9,000."
    c = Case(id="a", input="q", expected=exp, context=(ContextDoc("news", press),))
    assert check_answer_bearing(c)


def test_answer_bearing_threshold_is_configurable():
    partial = "the claim is accepted"
    c = mk([("news", partial)])
    assert check_answer_bearing(c, threshold=0.9) == []
    assert check_answer_bearing(c, threshold=0.1) != []


def test_whole_text_trap_report():
    trap_exp = "Objection rejected. Plea rejected.\nThe court rules: the claim is accepted."
    cases = [
        Case(id="t", input="q", expected=trap_exp),
        Case(id="ok", input="q", expected=EXPECTED),
    ]
    outputs = {"t": trap_exp, "ok": "The court rules: the claim is rejected."}
    r = whole_text_trap(cases, outputs)
    assert [d["case_id"] for d in r.dataset_disagreements] == ["t"]
    assert r.n_scored == 2 and r.operative_correct == 1 and r.naive_correct == 0


def test_guards_disabled():
    c = mk([("judg-1", EXPECTED)])
    cfg = GuardConfig(
        self_retrieval={"enabled": False},
        answer_bearing={"enabled": False},
        whole_text_trap={"enabled": False},
    )
    r = run_guards([c], cfg)
    assert r.findings == [] and r.trap is None and not r.leaky


# --- checkpoint: every seeded leak caught, no clean case flagged ----------------


def test_demo_guards_catch_every_seeded_leak_and_nothing_else(demo_config_path):
    cfg = load_config(demo_config_path)
    ds = load_dataset(cfg.dataset)
    report = run_guards(ds, cfg.guards)
    seeded = {
        c.id for c in ds if c.metadata.get("seeded_trap") in ("self_retrieval", "answer_bearing")
    }
    assert set(report.flagged_ids) == seeded
    by_guard = {SELF_RETRIEVAL: set(), ANSWER_BEARING: set()}
    for f in report.findings:
        by_guard[f.guard].add(f.case_id)
    self_seeded = {c.id for c in ds if c.metadata.get("seeded_trap") == "self_retrieval"}
    assert by_guard[SELF_RETRIEVAL] == self_seeded


def test_demo_guard_margin(demo_config_path):
    """Clean cases sit far below the thresholds, so the result isn't a knife-edge."""
    cfg = load_config(demo_config_path)
    ds = load_dataset(cfg.dataset)
    clean = [c for c in ds if c.metadata.get("seeded_trap") in (None, "whole_text")]
    worst_ab = max(
        (f.score for c in clean for f in check_answer_bearing(c, threshold=0.0)), default=0
    )
    worst_sr = max(
        (f.score for c in clean for f in check_self_retrieval(c, containment_min=0.0)), default=0
    )
    assert worst_ab < 0.3 and worst_sr < 0.3


@pytest.mark.parametrize("mode", ["fail", "exclude", "warn"])
def test_guard_report_mode_roundtrip(mode):
    r = run_guards([mk([("judg-1", EXPECTED)])], GuardConfig(mode=mode))
    d = r.to_dict()
    assert d["mode"] == mode and d["flagged"] == ["c1"]
