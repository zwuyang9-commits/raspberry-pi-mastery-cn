import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("projects/10_durable_action_queue/main.py")


def run_cli(queue, *arguments):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--queue", str(queue), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def json_lines(output):
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_cli_enqueue_list_and_cancel_lifecycle(tmp_path):
    queue = tmp_path / "queue.jsonl"

    created = run_cli(queue, "enqueue", "fan", "set", "1", "--id", "cli-action")
    listed = run_cli(queue, "list")
    cancelled = run_cli(
        queue,
        "cancel",
        "cli-action",
        "--reason",
        "maintenance",
    )

    assert json_lines(created.stdout) == [
        {"action_id": "cli-action", "status": "pending"}
    ]
    assert json_lines(listed.stdout)[0]["action_id"] == "cli-action"
    assert json_lines(cancelled.stdout) == [
        {"action_id": "cli-action", "status": "cancelled"}
    ]
    assert run_cli(queue, "list").stdout == ""


def test_cli_failure_exposes_retry_and_lease_state(tmp_path):
    queue = tmp_path / "queue.jsonl"
    run_cli(queue, "enqueue", "fan", "set", "1", "--id", "retry-cli")

    result = run_cli(
        queue,
        "run-demo",
        "--fail-target",
        "fan",
        "--retry-delay",
        "30",
        "--lease-seconds",
        "15",
    )
    [pending] = json_lines(run_cli(queue, "list").stdout)

    assert json_lines(result.stdout)[-1]["failed"] == ["retry-cli"]
    assert pending["attempts"] == 1
    assert pending["last_error"] == "模拟设备离线"
    assert pending["next_attempt_at"] is not None
    assert pending["lease_expires_at"] is None


def test_cli_terminal_archive_preview_and_apply(tmp_path):
    queue = tmp_path / "queue.jsonl"
    archive = tmp_path / "archive.jsonl"
    run_cli(queue, "enqueue", "fan", "set", "1", "--id", "archive-cli")
    run_cli(queue, "run-demo")

    preview = run_cli(
        queue,
        "archive-terminal",
        "2999-01-01T00:00:00+00:00",
        str(archive),
    )
    applied = run_cli(
        queue,
        "archive-terminal",
        "2999-01-01T00:00:00+00:00",
        str(archive),
        "--apply",
    )

    assert json_lines(preview.stdout)[0]["applied"] is False
    assert not archive.exists() or json_lines(applied.stdout)[0]["applied"] is True
    assert archive.exists()
    assert "queued_action_archived" in queue.read_text(encoding="utf-8")
