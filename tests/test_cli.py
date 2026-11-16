import json
import os
import subprocess
import sys
from pathlib import Path

from evalgate.cli import EXIT_ERROR, EXIT_OK, main


def write(tmp_path, *records, name="golden.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_validate_ok(tmp_path, capsys):
    path = write(tmp_path, {"id": "a", "input": "q", "expected": "x"})
    assert main(["validate", str(path)]) == EXIT_OK
    assert "ok: 1 case(s)" in capsys.readouterr().out


def test_validate_schema_error(tmp_path, capsys):
    path = write(tmp_path, {"id": "a", "input": "q"})
    assert main(["validate", str(path)]) == EXIT_ERROR
    assert "missing required field 'expected'" in capsys.readouterr().err


def test_validate_missing_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.jsonl")]) == EXIT_ERROR
    assert "no such file" in capsys.readouterr().err


def test_no_command_prints_help(capsys):
    assert main([]) == EXIT_ERROR
    assert "usage: evalgate" in capsys.readouterr().out


def test_module_entry_point():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "evalgate", "--version"],
        capture_output=True,
        text=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    assert result.returncode == 0
    assert result.stdout.startswith("evalgate ")
