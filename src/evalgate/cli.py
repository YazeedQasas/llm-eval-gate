"""The `evalgate` command.

Exit codes (stable, CI depends on them):
  0  pass
  1  regression found (the gate failed)
  2  could not run cleanly: usage, config, schema, missing recording, incomparable
     baseline, or leakage in guard mode 'fail'
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from evalgate import __version__
from evalgate.adapters import CacheMiss
from evalgate.compare import IncomparableError, compare
from evalgate.config import Config, ConfigError, load_config
from evalgate.guards import run_guards
from evalgate.offline import NetworkBlocked, no_network
from evalgate.pipeline import LeakageError, evaluate, read_results, write_results
from evalgate.report import check_report, guard_report_md, guard_section, summary_section
from evalgate.runner import (
    dataset_for,
    generate_all,
    read_outputs,
    record,
    replay_adapter,
    write_outputs,
)
from evalgate.schema import SchemaError, read_cases

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_ERROR = 2


def _config(args: argparse.Namespace) -> Config:
    return load_config(args.config).with_prompt(getattr(args, "prompt", None))


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        cases = read_cases(args.dataset)
    except FileNotFoundError:
        print(f"error: no such file: {args.dataset}", file=sys.stderr)
        return EXIT_ERROR
    print(f"ok: {len(cases)} case(s) in {args.dataset}")
    return EXIT_OK


def _cmd_record(args: argparse.Namespace) -> int:
    cfg = _config(args)
    n = record(cfg)
    print(
        f"recorded {n} case(s) for {cfg.system.name}@{cfg.system.prompt_version()} "
        f"into {cfg.system.recordings}"
    )
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = _config(args)
    dataset = dataset_for(cfg)
    with no_network():
        outputs = generate_all(replay_adapter(cfg), dataset)
    write_outputs(outputs, args.out)
    print(
        f"replayed {len(outputs)} output(s) for {cfg.system.name}@{cfg.system.prompt_version()} "
        f"(network blocked) -> {args.out}"
    )
    return EXIT_OK


def _cmd_guard(args: argparse.Namespace) -> int:
    cfg = _config(args)
    dataset = dataset_for(cfg)
    outputs = None
    try:
        with no_network():
            outputs = generate_all(replay_adapter(cfg), dataset)
    except CacheMiss:
        pass  # dataset-only guards still run
    report = run_guards(dataset, cfg.guards, outputs)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(guard_report_md(report), end="")
    return EXIT_ERROR if report.leaky and cfg.guards.mode == "fail" else EXIT_OK


def _cmd_score(args: argparse.Namespace) -> int:
    cfg = _config(args)
    outputs = read_outputs(args.outputs) if args.outputs else None
    ev = evaluate(cfg, outputs)
    write_results(ev.results, args.out)
    md = summary_section(ev.results, heading="#") + guard_section(ev.guard_report)
    print("\n".join(md).rstrip())
    print(f"\nresults -> {args.out}")
    return EXIT_OK


def _cmd_freeze(args: argparse.Namespace) -> int:
    cfg = _config(args)
    ev = evaluate(cfg)
    out = Path(args.out) if args.out else cfg.gate.baseline
    write_results(ev.results, out)
    agg = ev.results["aggregates"][cfg.gate.primary]
    print(
        f"froze baseline for prompt {cfg.system.prompt_version()}: {cfg.gate.primary} "
        f"{agg['pass_rate']:.1%} on {agg['n']} case(s) "
        f"({len(ev.results['excluded'])} excluded by guards) -> {out}"
    )
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    cfg = _config(args)
    baseline = read_results(Path(args.baseline) if args.baseline else cfg.gate.baseline)
    ev = evaluate(cfg)
    comp = compare(baseline, ev.results, cfg.gate)
    md = check_report(comp, ev.results, ev.guard_report)
    print(md, end="")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(md, encoding="utf-8", newline="\n")
    if args.results:
        write_results(ev.results, args.results)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return EXIT_OK if comp.passed else EXIT_REGRESSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalgate",
        description="Offline regression gates for LLM systems.",
        epilog="Exit codes: 0 pass, 1 regression, 2 could not run cleanly.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def with_config(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("-c", "--config", default="evalgate.toml", help="Path to evalgate.toml.")
        p.add_argument("--prompt", help="Use this prompt file instead of [system] prompt.")
        return p

    p = sub.add_parser("validate", help="Validate a golden dataset (JSONL).")
    p.add_argument("dataset", help="Path to a .jsonl golden dataset.")
    p.set_defaults(func=_cmd_validate)

    p = with_config(sub.add_parser("record", help="Call the live system and record outputs."))
    p.set_defaults(func=_cmd_record)

    p = with_config(sub.add_parser("run", help="Replay recorded outputs (offline)."))
    p.add_argument("--out", default="runs/outputs.jsonl", help="Where to write outputs.")
    p.set_defaults(func=_cmd_run)

    p = with_config(sub.add_parser("guard", help="Check the dataset for leakage."))
    p.add_argument("--json", action="store_true", help="Print the report as JSON.")
    p.set_defaults(func=_cmd_guard)

    p = with_config(sub.add_parser("score", help="Guard and score outputs."))
    p.add_argument("--outputs", help="Score this outputs file instead of replaying.")
    p.add_argument("--out", default="runs/results.json", help="Where to write results.")
    p.set_defaults(func=_cmd_score)

    p = with_config(sub.add_parser("freeze", help="Freeze current scores as the baseline."))
    p.add_argument("--out", help="Baseline path (default: [gate] baseline).")
    p.set_defaults(func=_cmd_freeze)

    p = with_config(sub.add_parser("check", help="The CI gate: guard, score, compare."))
    p.add_argument("--baseline", help="Baseline path (default: [gate] baseline).")
    p.add_argument("--report", help="Also write the markdown report here.")
    p.add_argument("--results", help="Also write this run's results JSON here.")
    p.set_defaults(func=_cmd_check)

    return parser


def _utf8_stdio() -> None:
    # Windows consoles default to a legacy code page; Arabic output must not crash.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return args.func(args)
    except LeakageError as exc:
        print(f"error: leakage: {exc}", file=sys.stderr)
        print("run `evalgate guard` for details, or set [guards] mode", file=sys.stderr)
        return EXIT_ERROR
    except IncomparableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (ConfigError, SchemaError, CacheMiss, NetworkBlocked) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
