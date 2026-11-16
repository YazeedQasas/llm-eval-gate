"""End-to-end on the shipped demo: replay, guards, freeze, compare, CLI exit codes."""

import json
import shutil
import socket

import pytest

from evalgate.cli import EXIT_ERROR, EXIT_OK, EXIT_REGRESSION, main
from evalgate.config import ConfigError, load_config
from evalgate.pipeline import LeakageError, dump_results, evaluate

from .conftest import DEMO


@pytest.fixture
def demo_copy(tmp_path):
    """A writable copy of the demo so tests can freeze baselines and edit config."""
    dst = tmp_path / "judgments"
    shutil.copytree(DEMO, dst, ignore=shutil.ignore_patterns("__pycache__", "baselines"))
    return dst


def edit_config(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_replay_runs_with_network_blocked(demo_config_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "create_connection", boom)
    ev = evaluate(load_config(demo_config_path))
    assert len(ev.outputs) == 72


def test_both_prompts_have_recordings(demo_config_path, v2_prompt):
    cfg = load_config(demo_config_path)
    assert len(evaluate(cfg).outputs) == 72
    assert len(evaluate(cfg.with_prompt(v2_prompt)).outputs) == 72


def test_evaluate_is_byte_reproducible(demo_config_path):
    cfg = load_config(demo_config_path)
    assert dump_results(evaluate(cfg).results) == dump_results(evaluate(cfg).results)


def test_committed_baseline_matches_fresh_freeze(demo_config_path):
    cfg = load_config(demo_config_path)
    assert cfg.gate.baseline.read_text(encoding="utf-8") == dump_results(evaluate(cfg).results)


def test_exclude_mode_drops_flagged_cases(demo_config_path):
    ev = evaluate(load_config(demo_config_path))
    assert len(ev.results["excluded"]) == 16 and len(ev.results["cases"]) == 56


def test_leaks_inflate_scores_when_not_excluded(demo_copy):
    cfg_path = demo_copy / "evalgate.toml"
    clean = evaluate(load_config(cfg_path)).results["aggregates"]["operative_verdict"]
    edit_config(cfg_path, 'mode = "exclude"', 'mode = "warn"')
    leaky = evaluate(load_config(cfg_path)).results["aggregates"]["operative_verdict"]
    assert leaky["n"] == 72 and leaky["pass_rate"] > clean["pass_rate"]


def test_fail_mode_raises_on_leaks(demo_copy):
    cfg_path = demo_copy / "evalgate.toml"
    edit_config(cfg_path, 'mode = "exclude"', 'mode = "fail"')
    with pytest.raises(LeakageError, match="16 case"):
        evaluate(load_config(cfg_path))


def test_naive_primary_refused(demo_copy):
    cfg_path = demo_copy / "evalgate.toml"
    edit_config(cfg_path, 'name = "normalized_match"', 'name = "whole_text_verdict"')
    edit_config(cfg_path, 'primary = "operative_verdict"', 'primary = "whole_text_verdict"')
    with pytest.raises(ConfigError, match="whole-text trap"):
        evaluate(load_config(cfg_path))


# --- CLI ------------------------------------------------------------------------


def test_cli_check_passes_on_baseline_prompt(demo_config_path, capsys):
    assert main(["check", "-c", str(demo_config_path)]) == EXIT_OK
    assert "evalgate: PASS" in capsys.readouterr().out


def test_cli_check_fails_on_better_looking_prompt(demo_config_path, v2_prompt, tmp_path, capsys):
    report = tmp_path / "report.md"
    code = main(
        ["check", "-c", str(demo_config_path), "--prompt", str(v2_prompt), "--report", str(report)]
    )
    assert code == EXIT_REGRESSION
    md = report.read_text(encoding="utf-8")
    assert "evalgate: FAIL" in md and "Regressed cases" in md
    assert "no operative line in output" in md


def test_cli_check_writes_github_summary(demo_config_path, v2_prompt, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    main(["check", "-c", str(demo_config_path), "--prompt", str(v2_prompt)])
    assert "evalgate: FAIL" in summary.read_text(encoding="utf-8")


def test_cli_freeze_then_check(demo_copy, capsys):
    cfg = str(demo_copy / "evalgate.toml")
    assert main(["check", "-c", cfg]) == EXIT_ERROR  # no baseline yet
    assert "evalgate freeze" in capsys.readouterr().err
    assert main(["freeze", "-c", cfg]) == EXIT_OK
    assert (demo_copy / "baselines" / "main.json").exists()
    assert main(["check", "-c", cfg]) == EXIT_OK


def test_cli_check_refuses_changed_dataset(demo_copy, capsys):
    cfg = str(demo_copy / "evalgate.toml")
    main(["freeze", "-c", cfg])
    cases = demo_copy / "cases.jsonl"
    lines = cases.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["tags"].append("edited")
    lines[0] = json.dumps(rec, ensure_ascii=False)
    cases.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["check", "-c", cfg]) == EXIT_ERROR
    assert "the dataset changed" in capsys.readouterr().err


def test_cli_missing_recording_is_exit_2(demo_copy, capsys):
    prompt = demo_copy / "prompts" / "judgment.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nBe concise.\n", encoding="utf-8")
    out = str(demo_copy / "out.jsonl")
    assert main(["run", "-c", str(demo_copy / "evalgate.toml"), "--out", out]) == EXIT_ERROR
    assert "re-record" in capsys.readouterr().err


def test_cli_guard_fail_mode_exit_2(demo_copy, capsys):
    cfg_path = demo_copy / "evalgate.toml"
    edit_config(cfg_path, 'mode = "exclude"', 'mode = "fail"')
    assert main(["guard", "-c", str(cfg_path)]) == EXIT_ERROR
    assert "16 of 72 case(s) flagged" in capsys.readouterr().out


def test_cli_guard_json(demo_config_path, capsys):
    assert main(["guard", "-c", str(demo_config_path), "--json"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert len(data["flagged"]) == 16


def test_cli_run_and_score(demo_config_path, tmp_path, capsys):
    out = tmp_path / "outputs.jsonl"
    assert main(["run", "-c", str(demo_config_path), "--out", str(out)]) == EXIT_OK
    res = tmp_path / "results.json"
    assert (
        main(["score", "-c", str(demo_config_path), "--outputs", str(out), "--out", str(res)])
        == EXIT_OK
    )
    assert json.loads(res.read_text(encoding="utf-8"))["aggregates"]["operative_verdict"]["n"] == 56


def test_cli_record_is_idempotent(demo_copy):
    cfg = str(demo_copy / "evalgate.toml")
    before = (demo_copy / "recordings.jsonl").read_bytes()
    assert main(["record", "-c", cfg]) == EXIT_OK
    assert (demo_copy / "recordings.jsonl").read_bytes() == before
