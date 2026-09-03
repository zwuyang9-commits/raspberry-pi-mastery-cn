"""Cross-process CLI workflows with isolated data and no physical hardware."""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(tmp_path, relative, *args, expected=0):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / relative), *map(str, args)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return result.stdout


def test_backup_cli_roundtrip(tmp_path):
    cli = "projects/08_verified_local_backup/main.py"
    source = tmp_path / "source"
    source.mkdir()
    payload = bytes(range(256)) * 17
    (source / "sample.bin").write_bytes(payload)
    archive = tmp_path / "backup.zip"
    run_cli(tmp_path, cli, "--root", source, "create", archive, "sample.bin")
    run_cli(tmp_path, cli, "verify", archive)
    run_cli(tmp_path, cli, "drill", archive)
    restored = tmp_path / "restored"
    run_cli(tmp_path, cli, "restore", archive, restored)
    assert (restored / "sample.bin").read_bytes() == payload
    assert (source / "sample.bin").read_bytes() == payload


def test_queue_cli_restart_and_dead_letter_recovery(tmp_path):
    cli = "projects/10_durable_action_queue/main.py"
    queue = tmp_path / "queue.jsonl"

    def invoke(*args, expected=0):
        return run_cli(tmp_path, cli, "--queue", queue, *args, expected=expected)

    assert json.loads(invoke("status"))["pending"] == 0
    assert not queue.exists()
    invoke("enqueue", "fan", "set", "true", "--id", "first")
    assert json.loads(invoke("status"))["pending"] == 1
    invoke("run-demo", "--fail-target", "fan", "--max-attempts", "1")
    assert json.loads(invoke("status", "--fail-on-dead", expected=1))["dead_letters"] == 1
    invoke("requeue", "first", "--new-id", "recovered")
    invoke("run-demo")
    state = json.loads(invoke("status"))
    assert state["pending"] == 0
    assert state["dead_letters"] == 1  # Original failure remains auditable.
    assert invoke("list") == ""


def test_console_audit_cli_workflow(tmp_path):
    console = "projects/07_local_operations_console/main.py"
    audit = tmp_path / "operations.jsonl"
    assert isinstance(json.loads(run_cli(tmp_path, console, "--audit-log", audit, "--json")), dict)
    metrics = run_cli(tmp_path, console, "--audit-log", audit, "--prometheus")
    assert "# HELP" in metrics
    before = audit.read_bytes()
    summary = json.loads(run_cli(
        tmp_path, "projects/09_local_audit_explorer/main.py", audit, "--summary"
    ))
    assert summary["entries"] > 0
    assert audit.read_bytes() == before


def test_environment_cli_appends_samples(tmp_path):
    cli = "projects/02_environment_station/main.py"
    output = tmp_path / "environment.csv"
    for _ in range(2):
        run_cli(tmp_path, cli, "--sensor", "simulated", "--samples", "2",
                "--interval", "0.001", "--output", output)
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    for row in rows:
        assert -40 <= float(row["temperature_c"]) <= 85
        assert 0 <= float(row["humidity_pct"]) <= 100


@pytest.mark.parametrize("relative,args", [
    ("projects/01_led_breathing/main.py", ["--simulate", "--cycles", "1"]),
    ("projects/05_resilient_home_hub/main.py", ["--simulate"]),
    ("projects/06_local_energy_scheduler/main.py", []),
])
def test_safe_demo_cli(tmp_path, relative, args):
    run_cli(tmp_path, relative, *args)
