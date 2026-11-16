import ast
import inspect

import pytest

import evalgate.normalize
import evalgate.operative
import evalgate.scorers
from evalgate.config import ConfigError, ScorerSpec
from evalgate.normalize import containment, normalize_arabic, normalize_text
from evalgate.operative import (
    ACCEPTED,
    DISMISSED,
    PARTIAL,
    REJECTED,
    categorize,
    extract_operative_line,
    operative_verdict,
    whole_text_verdict,
)
from evalgate.schema import Case
from evalgate.scorers import (
    REGISTRY,
    ScoreResult,
    aggregate,
    build_scorer,
    score_outputs,
    scorers_fingerprint,
)


def case(expected, tags=(), cid="c1"):
    return Case(id=cid, input="q", expected=expected, tags=tuple(tags))


def run(name, expected, output, **options):
    return build_scorer(ScorerSpec(name, options)).score(case(expected), output)


# --- normalization -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "norm"),
    [
        ("أحمد", "احمد"),
        ("إسلام", "اسلام"),
        ("آمنة", "امنه"),
        ("مستشفى", "مستشفي"),
        ("مَحْكَمَةٌ", "محكمه"),
        ("محكـــمة", "محكمه"),
    ],
)
def test_arabic_normalization(raw, norm):
    assert normalize_arabic(raw) == norm


def test_normalize_text_full():
    assert normalize_text("  The COURT,  rules:\n accepted! ") == "the court rules accepted"
    assert normalize_text("حَكَمَت المحكمةُ، بقبولِ الدعوى؟") == "حكمت المحكمه بقبول الدعوي"
    assert normalize_text("المبلغ ٤٥٠٠") == "المبلغ 4500"


def test_containment():
    assert containment("a b c d", "x a b c d y", 2) == 1.0
    assert containment("a b c d", "a b x c d", 2) == pytest.approx(2 / 3)
    assert containment("", "anything", 3) == 0.0


# --- operative line -------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "verdict"),
    [
        ("The court rules: the claim is accepted.", ACCEPTED),
        ("The court rules: the claim is partially accepted; the rest is rejected.", PARTIAL),
        ("The court rules: the claim is rejected.", REJECTED),
        ("The court rules: the claim is inadmissible.", DISMISSED),
        ("حكمت المحكمة بقبول الدعوى", ACCEPTED),
        ("حكمت المحكمة بقبول الدعوى جزئياً ورد ما زاد", PARTIAL),
        ("حكمت المحكمة برد الدعوى", REJECTED),
        ("حكمت المحكمة بعدم قبول الدعوى", DISMISSED),
        ("The court rules as follows.", None),
    ],
)
def test_categorize(line, verdict):
    assert categorize(line) == verdict


def test_last_operative_line_wins():
    text = (
        "Reasoning: the first-instance court rules: the claim is rejected, which we review.\n"
        "The court rules: the appeal succeeds and the claim is accepted."
    )
    line = extract_operative_line(text)
    assert line.line_no == 2 and categorize(line.text) == ACCEPTED


def test_marker_mid_line():
    line = extract_operative_line("Analysis done. The court rules: the claim is rejected.")
    assert line.text == "The court rules: the claim is rejected."


def test_marker_line_without_verdict_joins_next_line():
    text = "الأسباب: ثبت الإخلال.\nلهذه الأسباب\n\nبقبول الدعوى وإلزام المدعى عليه."
    verdict, line = operative_verdict(text)
    assert verdict == ACCEPTED and line.line_no == 2
    assert line.text == "لهذه الأسباب بقبول الدعوى وإلزام المدعى عليه."


def test_no_operative_line():
    assert operative_verdict("In light of the foregoing the claimant should prevail.") == (
        None,
        None,
    )


def test_reasoning_contradicting_verdict_english():
    text = (
        "Reasoning: the objection is rejected. The adjournment is rejected. The plea is "
        "rejected.\nThe court rules: the claim is accepted."
    )
    assert operative_verdict(text)[0] == ACCEPTED
    assert whole_text_verdict(text) == REJECTED  # the trap


def test_reasoning_contradicting_verdict_arabic():
    text = (
        "الأسباب: وتقرر رفض الدفع، وتقرر رفض الطلب، وتقرر رفض التأجيل.\nحكمت المحكمة بقبول الدعوى."
    )
    assert operative_verdict(text)[0] == ACCEPTED
    assert whole_text_verdict(text) == REJECTED


# --- scorers --------------------------------------------------------------------


def test_exact_match():
    assert run("exact_match", "abc", " abc\n").passed
    assert not run("exact_match", "abc", "ABC").passed


def test_normalized_match():
    assert run("normalized_match", "The claim, accepted.", "the claim accepted").passed
    assert run("normalized_match", "حكمت المحكمة", "حَكَمَت المحكمه").passed
    assert not run("normalized_match", "accepted", "rejected").passed


def test_regex_match():
    opts = {"pattern": r"amount of ([\d,]+)"}
    assert run("regex_match", "pay an amount of 4,500 now", "an amount of 4,500.", **opts).passed
    r = run("regex_match", "pay an amount of 4,500", "an amount of 9,000", **opts)
    assert not r.passed and "9 000" in r.reason  # normalized: punctuation -> space
    assert "not found in output" in run("regex_match", "amount of 1", "none", **opts).reason
    assert "not found in expected" in run("regex_match", "none", "amount of 1", **opts).reason


def test_regex_bad_pattern():
    with pytest.raises(ConfigError, match="bad pattern"):
        build_scorer(ScorerSpec("regex_match", {"pattern": "("}))


def test_label_set_f1():
    r = run("label_set_f1", "lease, rent, damages", "rent, lease")
    assert r.score == pytest.approx(0.8) and not r.passed
    assert run("label_set_f1", "a, b", "B , a").passed
    assert run("label_set_f1", "a, b", "a", threshold=0.6).passed
    assert run("label_set_f1", "a", "x").score == 0.0


def test_operative_verdict_scorer():
    exp = "Reasoning: x.\nThe court rules: the claim is accepted."
    assert run("operative_verdict", exp, "Short.\nThe court rules: the claim is accepted.").passed
    r = run("operative_verdict", exp, "The court rules: the claim is rejected.")
    assert not r.passed and r.reason.startswith("got rejected, expected accepted")


def test_operative_verdict_fails_without_operative_line():
    exp = "The court rules: the claim is accepted."
    r = run("operative_verdict", exp, "The claim is accepted, clearly.")
    assert not r.passed and r.reason == "no operative line in output"


def test_operative_verdict_flags_bad_golden_answer():
    r = run("operative_verdict", "no ruling here", "The court rules: the claim is accepted.")
    assert not r.passed and "fix the dataset" in r.reason


def test_operative_verdict_ignores_contradicting_reasoning():
    exp = "Reasoning: x.\nThe court rules: the claim is accepted."
    out = (
        "Objection rejected. Adjournment rejected. Plea rejected.\n"
        "The court rules: the claim is accepted."
    )
    assert run("operative_verdict", exp, out).passed
    assert not run("whole_text_verdict", exp, out).passed


def test_unknown_scorer_and_bad_options():
    with pytest.raises(ConfigError, match="unknown scorer"):
        build_scorer(ScorerSpec("nope"))
    with pytest.raises(ConfigError, match="bad options"):
        build_scorer(ScorerSpec("exact_match", {"bogus": 1}))


def test_fingerprint_changes_with_options_and_version(monkeypatch):
    a = scorers_fingerprint([ScorerSpec("label_set_f1", {"threshold": 1.0})])
    b = scorers_fingerprint([ScorerSpec("label_set_f1", {"threshold": 0.5})])
    assert a != b
    monkeypatch.setattr(REGISTRY["label_set_f1"], "version", "2")
    assert scorers_fingerprint([ScorerSpec("label_set_f1", {"threshold": 1.0})]) != a


def test_score_outputs_and_aggregate():
    cases = [
        case("The court rules: the claim is accepted.", ["english"], "a"),
        case("The court rules: the claim is rejected.", ["english", "lease"], "b"),
        case("The court rules: the claim is rejected.", ["lease"], "c"),
    ]
    outputs = {
        "a": "The court rules: the claim is accepted.",
        "b": "The court rules: the claim is accepted.",
    }
    scorer = build_scorer(ScorerSpec("operative_verdict"))
    res = score_outputs(cases, outputs, [scorer])
    assert res["c"]["operative_verdict"] == ScoreResult(0.0, False, "no output")
    agg = aggregate(cases, res)["operative_verdict"]
    assert agg["n"] == 3 and agg["passed"] == 1 and agg["pass_rate"] == pytest.approx(1 / 3)
    assert agg["tags"]["english"]["pass_rate"] == 0.5
    assert agg["tags"]["lease"]["pass_rate"] == 0.0


# --- determinism ----------------------------------------------------------------

SAMPLES = [
    (
        "The court rules: the claim is accepted.",
        "Reasons.\nThe court rules: the claim is accepted.",
    ),
    ("حكمت المحكمة برد الدعوى", "الأسباب: رفض.\nحكمت المحكمة بقبول الدعوى"),
    ("a, b, c", "c, a"),
]


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_same_input_same_score_100_runs(name):
    options = {"pattern": r"(\w+)"} if name == "regex_match" else {}
    scorer = build_scorer(ScorerSpec(name, options))
    for expected, output in SAMPLES:
        c = case(expected)
        first = scorer.score(c, output)
        assert all(scorer.score(c, output) == first for _ in range(100))


FORBIDDEN_MODULES = {"random", "time", "datetime", "socket", "urllib", "http", "secrets", "uuid"}


@pytest.mark.parametrize("module", [evalgate.scorers, evalgate.operative, evalgate.normalize])
def test_scorer_modules_import_no_randomness_clock_or_network(module):
    tree = ast.parse(inspect.getsource(module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & FORBIDDEN_MODULES
