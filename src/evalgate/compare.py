"""Compare a run to a frozen baseline and decide whether the gate passes.

Decision rules (all on the primary scorer's per-case pass/fail):

1. Overall: fail if the pass rate drops by more than `max_drop` AND the paired exact
   test on flipped cases gives p < `alpha`. Both are needed: the threshold ignores
   tiny drops, the test ignores drops that a few coin-flip cases could explain.
2. Per tag (tags with at least `min_tag_cases` cases): same rule with `max_tag_drop`.
3. Hard cap: fail if more than `max_regressed` cases flip pass -> fail, regardless
   of significance (unset = no cap).

The paired test is an exact one-sided McNemar test: of the b + c cases that flipped,
b went pass -> fail. Under "no change" each flip is a fair coin, so
p = P(X >= b) for X ~ Binomial(b + c, 0.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import comb
from typing import Any

from evalgate.config import GateConfig


class IncomparableError(ValueError):
    """Baseline and run were produced from different datasets, scorers or eval config."""


def _exceeds(drop: float, limit: float) -> bool:
    """drop > limit, ignoring float noise: a drop of exactly the limit is allowed."""
    return drop - limit > 1e-9


def mcnemar_one_sided(regressed: int, fixed: int) -> float:
    """P(X >= regressed) for X ~ Binomial(regressed + fixed, 1/2). Exact."""
    n = regressed + fixed
    if n == 0 or regressed == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(regressed, n + 1))
    return tail / 2**n


@dataclass
class SliceDelta:
    name: str
    n: int
    base_rate: float
    cur_rate: float
    regressed: int
    fixed: int
    p_value: float

    @property
    def delta(self) -> float:
        return self.cur_rate - self.base_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "n": self.n,
            "base_rate": round(self.base_rate, 6),
            "cur_rate": round(self.cur_rate, 6),
            "delta": round(self.delta, 6),
            "regressed": self.regressed,
            "fixed": self.fixed,
            "p_value": round(self.p_value, 6),
        }


@dataclass
class Flip:
    case_id: str
    tags: list[str]
    base_reason: str
    cur_reason: str
    cur_operative_line: str | None


@dataclass
class Comparison:
    primary: str
    base_prompt: str
    cur_prompt: str
    overall: SliceDelta
    tags: list[SliceDelta]
    regressed: list[Flip]
    fixed: list[Flip]
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def check_comparable(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    bf, cf = baseline.get("fingerprint", {}), current.get("fingerprint", {})
    diffs = [k for k in sorted(set(bf) | set(cf)) if bf.get(k) != cf.get(k)]
    if baseline.get("primary") != current.get("primary"):
        diffs.append("primary")
    if diffs:
        what = {
            "dataset": "the dataset changed (cases, expected answers or tags)",
            "scorers": "the scorers changed (names, versions or options)",
            "eval_config": "the guard settings changed",
            "primary": "the primary scorer changed",
        }
        lines = [f"  - {what.get(d, d)}" for d in diffs]
        raise IncomparableError(
            "baseline is not comparable with this run:\n"
            + "\n".join(lines)
            + "\nRe-freeze the baseline on main (`evalgate freeze`) in the same change that "
            "alters the evaluation, so reviewers see both."
        )


def _passes(results: dict[str, Any], primary: str) -> dict[str, bool]:
    return {cid: c["scores"][primary]["passed"] for cid, c in results["cases"].items()}


def _slice(name: str, ids: list[str], base: dict[str, bool], cur: dict[str, bool]) -> SliceDelta:
    n = len(ids)
    b = sum(base[i] and not cur[i] for i in ids)
    c = sum(cur[i] and not base[i] for i in ids)
    return SliceDelta(
        name=name,
        n=n,
        base_rate=sum(base[i] for i in ids) / n if n else 0.0,
        cur_rate=sum(cur[i] for i in ids) / n if n else 0.0,
        regressed=b,
        fixed=c,
        p_value=mcnemar_one_sided(b, c),
    )


def compare(baseline: dict[str, Any], current: dict[str, Any], gate: GateConfig) -> Comparison:
    check_comparable(baseline, current)
    primary = gate.primary
    base, cur = _passes(baseline, primary), _passes(current, primary)
    if set(base) != set(cur):
        missing = sorted(set(base) ^ set(cur))[:10]
        raise IncomparableError(f"baseline and run scored different cases: {missing}")
    ids = sorted(base)

    def flip(cid: str) -> Flip:
        c = current["cases"][cid]
        return Flip(
            case_id=cid,
            tags=c["tags"],
            base_reason=baseline["cases"][cid]["scores"][primary]["reason"],
            cur_reason=c["scores"][primary]["reason"],
            cur_operative_line=c.get("operative_line"),
        )

    overall = _slice("overall", ids, base, cur)
    tag_ids: dict[str, list[str]] = {}
    for cid in ids:
        for t in current["cases"][cid]["tags"]:
            tag_ids.setdefault(t, []).append(cid)
    tags = [_slice(t, v, base, cur) for t, v in sorted(tag_ids.items())]

    comp = Comparison(
        primary=primary,
        base_prompt=baseline["system"]["prompt_version"],
        cur_prompt=current["system"]["prompt_version"],
        overall=overall,
        tags=tags,
        regressed=[flip(i) for i in ids if base[i] and not cur[i]],
        fixed=[flip(i) for i in ids if cur[i] and not base[i]],
    )

    if _exceeds(-overall.delta, gate.max_drop) and overall.p_value < gate.alpha:
        comp.failures.append(
            f"{primary} pass rate dropped {-overall.delta:.1%} "
            f"({overall.base_rate:.1%} -> {overall.cur_rate:.1%}), "
            f"limit {gate.max_drop:.1%}, p={overall.p_value:.4f} < {gate.alpha}"
        )
    for t in tags:
        if (
            t.n >= gate.min_tag_cases
            and _exceeds(-t.delta, gate.max_tag_drop)
            and t.p_value < gate.alpha
        ):
            comp.failures.append(
                f"tag '{t.name}' dropped {-t.delta:.1%} "
                f"({t.base_rate:.1%} -> {t.cur_rate:.1%}), limit {gate.max_tag_drop:.1%}, "
                f"p={t.p_value:.4f}"
            )
    if gate.max_regressed is not None and len(comp.regressed) > gate.max_regressed:
        comp.failures.append(
            f"{len(comp.regressed)} case(s) regressed (pass -> fail), limit {gate.max_regressed}"
        )
    return comp
