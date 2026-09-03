import json
import subprocess
from pathlib import Path

import pytest

from scripts.run_safe_demos import demo_commands, run_demos


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
