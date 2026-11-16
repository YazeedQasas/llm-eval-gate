from math import comb
from pathlib import Path

import pytest

from evalgate.compare import IncomparableError, compare, mcnemar_one_sided
from evalgate.config import GateConfig


def gate(**kw):
    defaults = dict(
        primary="s",
        baseline=Path("b.json"),
        max_drop=0.02,
        max_tag_drop=0.10,
        min_tag_cases=5,
        max_regressed=None,
        alpha=0.05,
    )
    defaults.update(kw)
    return GateConfig(**defaults)


def results(passes: dict[str, bool], tags=None, prompt="p1", fp=None):
    tags = tags or {}
    return {
        "fingerprint": fp or {"dataset": "d", "scorers": "s", "eval_config": "e"},
        "primary": "s",
        "system": {"prompt_version": prompt},
        "cases": {
            cid: {
                "tags": tags.get(cid, ["all"]),
                "operative_line": None,
                "scores": {"s": {"score": float(p), "passed": p, "reason": "r"}},
            }
            for cid, p in passes.items()
        },
    }


def flips(n_total, base_pass, regressed, fixed):
    """Build baseline/current pass maps with exact flip counts."""
    ids = [f"c{i:03d}" for i in range(n_total)]
    base = {i: k < base_pass for k, i in enumerate(ids)}
    cur = dict(base)
    passing = [i for i in ids if base[i]]
    failing = [i for i in ids if not base[i]]
    for i in passing[:regressed]:
        cur[i] = False
    for i in failing[:fixed]:
        cur[i] = True
    return base, cur


# --- the test itself -------------------------------------------------------------


@pytest.mark.parametrize(("b", "c"), [(0, 0), (0, 5), (1, 0), (5, 0), (13, 3), (7, 7)])
def test_mcnemar_matches_binomial_tail(b, c):
    n = b + c
    want = 1.0 if n == 0 or b == 0 else sum(comb(n, k) for k in range(b, n + 1)) / 2**n
    assert mcnemar_one_sided(b, c) == pytest.approx(want)


def test_mcnemar_known_values():
    assert mcnemar_one_sided(5, 0) == pytest.approx(1 / 32)
    assert mcnemar_one_sided(4, 0) == pytest.approx(1 / 16)  # not < 0.05
    assert mcnemar_one_sided(13, 3) == pytest.approx(0.010635, abs=1e-6)


# --- decisions ---------------------------------------------------------------------


def test_identical_runs_pass():
    base, _ = flips(50, 40, 0, 0)
    comp = compare(results(base), results(base), gate())
    assert comp.passed and comp.overall.delta == 0


def test_big_significant_drop_fails():
    base, cur = flips(56, 46, 13, 3)
    comp = compare(results(base), results(cur, prompt="p2"), gate())
    assert not comp.passed
    assert len(comp.regressed) == 13 and len(comp.fixed) == 3
    assert "pass rate dropped" in comp.failures[0]


def test_drop_above_threshold_but_not_significant_passes():
    # 4 regressions, 0 fixes: drop 8% > 2% but p = 1/16 > 0.05 -> noise, pass
    base, cur = flips(50, 40, 4, 0)
    comp = compare(results(base), results(cur), gate())
    assert comp.overall.p_value == pytest.approx(1 / 16)
    assert comp.passed


def test_significant_but_below_threshold_passes():
    # 5 flips on 1000 cases is significant (p=1/32) but only a 0.5-point drop
    base, cur = flips(1000, 800, 5, 0)
    comp = compare(results(base), results(cur), gate())
    assert comp.overall.p_value < 0.05 and -comp.overall.delta < 0.02
    assert comp.passed


def test_borderline_exactly_at_threshold_passes():
    # drop exactly max_drop is allowed ("more than" fails)
    base, cur = flips(100, 80, 2, 0)
    comp = compare(results(base), results(cur), gate(max_drop=0.02, alpha=1.0))
    assert -comp.overall.delta == pytest.approx(0.02) and comp.passed
    base, cur = flips(100, 80, 3, 0)
    assert not compare(results(base), results(cur), gate(max_drop=0.02, alpha=1.0)).passed


def test_regressions_offset_by_fixes_pass():
    base, cur = flips(50, 30, 6, 6)
    comp = compare(results(base), results(cur), gate())
    assert comp.overall.delta == 0 and comp.passed


def test_max_regressed_cap_fails_even_when_not_significant():
    base, cur = flips(50, 30, 6, 6)
    comp = compare(results(base), results(cur), gate(max_regressed=5))
    assert not comp.passed and "6 case(s) regressed" in comp.failures[0]


def test_tag_drop_fails_when_large_enough():
    base, cur = flips(60, 50, 6, 0)
    tags = {cid: (["arabic"] if k < 20 else ["english"]) for k, cid in enumerate(sorted(base))}
    # all 6 regressions fall in the first 20 cases -> the arabic tag
    comp = compare(results(base, tags), results(cur, tags), gate(max_drop=0.5))
    assert any("tag 'arabic'" in f for f in comp.failures)
    assert not any("tag 'english'" in f for f in comp.failures)


def test_small_tags_are_ignored():
    base, cur = flips(60, 50, 6, 0)
    tags = {cid: (["tiny"] if k < 6 else ["rest"]) for k, cid in enumerate(sorted(base))}
    comp = compare(results(base, tags), results(cur, tags), gate(max_drop=0.5, min_tag_cases=10))
    assert not any("tiny" in f for f in comp.failures)


def test_hash_mismatch_refused_with_reason():
    base, _ = flips(10, 5, 0, 0)
    other = results(base, fp={"dataset": "OTHER", "scorers": "s", "eval_config": "e"})
    with pytest.raises(IncomparableError, match="the dataset changed"):
        compare(results(base), other, gate())


def test_scorer_mismatch_refused():
    base, _ = flips(10, 5, 0, 0)
    other = results(base, fp={"dataset": "d", "scorers": "X", "eval_config": "e"})
    with pytest.raises(IncomparableError, match="scorers changed"):
        compare(results(base), other, gate())


def test_different_case_sets_refused():
    base, _ = flips(10, 5, 0, 0)
    fewer = dict(list(base.items())[:9])
    with pytest.raises(IncomparableError, match="different cases"):
        compare(results(base), results(fewer), gate())
