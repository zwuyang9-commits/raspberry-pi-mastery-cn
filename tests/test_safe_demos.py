import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scripts.run_safe_demos import ROOT, demo_commands, live_log, run_demos, select_commands


def test_commands_are_isolated_and_simulated(tmp_path):
    commands = dict(demo_commands(tmp_path))
    assert len(commands) == 6
    assert "--simulate" in commands["led-simulated"]
    assert "--simulate" in commands["home-hub-simulated"]
    assert "simulated" in commands["environment-simulated"]
    assert str(tmp_path / "audit.jsonl") in commands["operations"]
    assert all("--camera" not in command for command in commands.values())


def test_run_preserves_logs_and_reports_failure(monkeypatch, tmp_path):
    outcomes = iter([0, 1, "timeout", "launch", 0, 0])

    def run(command, **kwargs):
        assert Path(command[1]).is_absolute()
        assert kwargs["cwd"] == tmp_path / "result"
        assert kwargs["timeout"] == 2
        kwargs["stdout"].write("diagnostic output\n")
        code = next(outcomes)
        if code == "timeout":
            raise subprocess.TimeoutExpired(command, 2)
        if code == "launch":
            raise OSError("missing executable")
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr("scripts.run_safe_demos.subprocess.run", run)
    output = tmp_path / "result"
    result = run_demos(output, 2)
    assert not result["ok"] and result["complete"]
    assert [item["status"] for item in result["steps"]] == [
        "passed",
        "failed",
        "timeout",
        "failed",
        "passed",
        "passed",
    ]
    assert json.loads((output / "summary.json").read_text()) == result
    assert "diagnostic output" in (output / "led-simulated.log").read_text()
    assert "Launch failed" in (output / "energy-plan.log").read_text()


def test_existing_output_never_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        run_demos(tmp_path)


@pytest.mark.parametrize("timeout", [0, -1, 301, float("nan"), float("inf")])
def test_invalid_timeout_creates_no_directory(tmp_path, timeout):
    output = tmp_path / "result"
    with pytest.raises(ValueError):
        run_demos(output, timeout)
    assert not output.exists()


def test_real_subprocess_demos(tmp_path):
    result = run_demos(tmp_path / "result")
    assert result["ok"]
    assert len(result["steps"]) == 6
    assert (tmp_path / "result/environment.csv").exists()


def test_selection_deduplicates_and_includes_dependencies(tmp_path):
    selected = select_commands(tmp_path, ["audit-summary", "energy-plan", "audit-summary"])
    assert [name for name, _ in selected] == ["energy-plan", "operations", "audit-summary"]


@pytest.mark.parametrize("steps", [[], ["unknown"], ["energy-plan", "unknown"]])
def test_invalid_selection_never_creates_output(tmp_path, steps):
    output = tmp_path / "run"
    with pytest.raises(ValueError):
        run_demos(output, steps=steps)
    assert not output.exists()


def test_live_log_streams_before_completion_and_decodes_utf8(tmp_path, monkeypatch):
    path = tmp_path / "stream.log"
    path.touch()
    chunks = []
    observed = threading.Event()

    def display(text, **kwargs):
        chunks.append(text)
        if "first" in text:
            observed.set()

    monkeypatch.setattr("scripts.run_safe_demos.print", display, raising=False)
    with live_log(path), path.open("ab", buffering=0) as writer:
        writer.write(b"first\n")
        assert observed.wait(3), "log must appear while the step is still running"
        encoded = "中文\n".encode()
        writer.write(encoded[:1])
        writer.write(encoded[1:])
    assert "".join(chunks) == "first\n中文\n"


def test_interruption_keeps_incomplete_summary(monkeypatch, tmp_path):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("scripts.run_safe_demos.subprocess.run", interrupt)
    output = tmp_path / "result"
    with pytest.raises(KeyboardInterrupt):
        run_demos(output, steps=["energy-plan"])
    summary = json.loads((output / "summary.json").read_text())
    assert not summary["complete"] and not summary["ok"]
    assert summary["planned_steps"] == ["energy-plan"]


def test_cli_listing_does_not_create_directory(tmp_path):
    output = tmp_path / "unused"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_safe_demos.py"),
            "--list",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [name for name, _ in demo_commands(tmp_path)]
    assert not output.exists()


def test_selected_audit_runs_real_dependency(tmp_path):
    output = tmp_path / "selected"
    summary = run_demos(output, steps=["audit-summary"])
    assert summary["ok"]
    assert [step["name"] for step in summary["steps"]] == ["operations", "audit-summary"]
    assert not (output / "environment.csv").exists()
