"""One evaluation: dataset -> replayed outputs -> guards -> scores -> results dict.

The results dict is the on-disk format for both runs and frozen baselines. It carries
no timestamps, so evaluating the same inputs twice gives byte-identical files.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalgate import __version__
from evalgate.config import Config, ConfigError
from evalgate.datasets import Dataset
from evalgate.guards import GuardReport, run_guards
from evalgate.offline import no_network
from evalgate.operative import extract_operative_line
from evalgate.runner import dataset_for, generate_all, replay_adapter
from evalgate.scorers import aggregate, build_scorers, score_outputs, scorers_fingerprint

RESULTS_FORMAT = 1


class LeakageError(RuntimeError):
    """Guards flagged leaky cases and [guards] mode is 'fail'."""

    def __init__(self, report: GuardReport):
        self.report = report
        super().__init__(
            f"{len(report.flagged_ids)} case(s) flagged for leakage: "
            + ", ".join(report.flagged_ids[:10])
            + (" ..." if len(report.flagged_ids) > 10 else "")
        )


@dataclass
class Evaluation:
    results: dict[str, Any]
    guard_report: GuardReport
    dataset: Dataset
    outputs: dict[str, str]


def fingerprint(config: Config, dataset: Dataset) -> dict[str, str]:
    """What must match for two results to be comparable. The prompt is deliberately
    not in here: comparing prompts is the point."""
    return {
        "dataset": dataset.hash,
        "scorers": scorers_fingerprint(config.scorers),
        "eval_config": config.eval_config_hash(),
    }


def _check_primary(config: Config) -> None:
    from evalgate.scorers import REGISTRY

    cls = REGISTRY.get(config.gate.primary)
    allow = bool(config.guards.whole_text_trap.get("allow_naive_primary", False))
    if cls is not None and getattr(cls, "naive", False) and not allow:
        raise ConfigError(
            f"primary scorer {config.gate.primary!r} is a whole-text categorizer and falls "
            "for the whole-text trap; use 'operative_verdict' (or set "
            "[guards] whole_text_trap.allow_naive_primary = true)"
        )


def evaluate(config: Config, outputs: Mapping[str, str] | None = None) -> Evaluation:
    """Run the whole evaluation offline. Raises LeakageError in guard mode 'fail'."""
    _check_primary(config)
    scorers = build_scorers(config.scorers)
    dataset = dataset_for(config)

    with no_network():
        if outputs is None:
            outputs = generate_all(replay_adapter(config), dataset)
        outputs = dict(outputs)
        report = run_guards(dataset, config.guards, outputs)

    if report.leaky and config.guards.mode == "fail":
        raise LeakageError(report)
    excluded = set(report.flagged_ids) if config.guards.mode == "exclude" else set()
    scored_cases = [c for c in dataset if c.id not in excluded]

    per_case = score_outputs(scored_cases, outputs, scorers)
    cases_out: dict[str, Any] = {}
    for case in scored_cases:
        line = extract_operative_line(outputs.get(case.id, ""))
        cases_out[case.id] = {
            "tags": list(case.tags),
            "operative_line": line.text if line else None,
            "scores": {name: r.to_dict() for name, r in per_case[case.id].items()},
        }

    results = {
        "format": RESULTS_FORMAT,
        "evalgate_version": __version__,
        "fingerprint": fingerprint(config, dataset),
        "system": {
            "name": config.system.name,
            "model": config.system.model,
            "prompt_version": config.system.prompt_version(),
            "prompt": _rel(config.system.prompt, config.root),
        },
        "dataset": {"path": _rel(Path(dataset.path), config.root), "n": len(dataset)},
        "primary": config.gate.primary,
        "guards": report.to_dict(),
        "excluded": sorted(excluded),
        "aggregates": aggregate(scored_cases, per_case),
        "cases": dict(sorted(cases_out.items())),
    }
    return Evaluation(results=results, guard_report=report, dataset=dataset, outputs=outputs)


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def dump_results(results: Mapping[str, Any]) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_results(results: Mapping[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_results(results), encoding="utf-8", newline="\n")


def read_results(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ConfigError(f"baseline not found: {p} (create one with `evalgate freeze`)") from None
    if data.get("format") != RESULTS_FORMAT:
        raise ConfigError(f"{p}: unsupported results format {data.get('format')!r}")
    return data
