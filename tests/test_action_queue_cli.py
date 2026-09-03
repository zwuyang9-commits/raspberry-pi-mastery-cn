import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rpi_mastery.action_queue import DurableActionQueue
from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action

SCRIPT = Path("projects/10_durable_action_queue/main.py")


def test_run_demo_json_success_and_default_output(tmp_path):
    path = tmp_path / "queue.jsonl"
    run_cli(path, "enqueue", "fan", "set", "true", "--id", "json-success")
    result = run_cli(path, "run-demo", "--json", "--fail-on-error")
    assert len(result.stdout.splitlines()) == 1
    report = json.loads(result.stdout)
    assert report["processed"] == 1
    assert report["completed"] == ["json-success"]
    assert report["failed"] == []
    run_cli(path, "enqueue", "fan", "set", "false", "--id", "legacy")
    assert "执行 legacy:" in run_cli(path, "run-demo").stdout


@pytest.mark.parametrize("strict", [False, True])
def test_run_demo_json_failure_reports_all_actions(tmp_path, strict):
    path = tmp_path / "queue.jsonl"
    run_cli(path, "enqueue", "fan", "set", "true", "--id", "bad")
    run_cli(path, "enqueue", "light", "set", "true", "--id", "good")
    args = ["run-demo", "--json", "--fail-target", "fan", "--max-attempts", "1"]
    if strict:
        with pytest.raises(subprocess.CalledProcessError) as error:
            run_cli(path, *args, "--fail-on-error")
        result = error.value
        assert result.returncode == 1
    else:
        result = run_cli(path, *args)
    assert result.stderr == ""
    assert len(result.stdout.splitlines()) == 1
    report = json.loads(result.stdout)
    assert report["processed"] == 2
    assert report["failed"] == ["bad"]
    assert report["completed"] == ["good"]
    assert report["dead_lettered"] == ["bad"]
    assert json.loads(run_cli(path, "status").stdout)["pending"] == 0
    # A historical dead letter is not a failure of the next empty run.
    empty = json.loads(run_cli(path, "run-demo", "--json", "--fail-on-error").stdout)
    assert empty["processed"] == 0


def test_run_demo_strict_preserves_retryable_failure(tmp_path):
    path = tmp_path / "queue.jsonl"
    run_cli(path, "enqueue", "fan", "set", "true", "--id", "retry")
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_cli(path, "run-demo", "--json", "--fail-target", "fan", "--fail-on-error")
    report = json.loads(error.value.stdout)
    assert report["failed"] == ["retry"]
    assert report["dead_lettered"] == []
    assert json.loads(run_cli(path, "status").stdout)["pending"] == 1


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


@pytest.mark.parametrize("command", ["list", "list-dead"])
def test_cli_list_filters_before_limit_without_mutation(tmp_path, command):
    path = tmp_path / "queue.jsonl"
    queue = DurableActionQueue(AuditLog(path))
    for index, target in enumerate(("pump", "fan", "Fan", "fan", "风扇")):
        queue.enqueue(Action(target, "set", 1, "test"), action_id=f"a{index}")
    if command == "list-dead":
        queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                       max_attempts=1)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    assert len(json_lines(run_cli(path, command).stdout)) == 5
    assert [item["action_id"] for item in json_lines(
        run_cli(path, command, "--target", "fan", "--limit", "1").stdout
    )] == ["a1"]
    assert [item["action_id"] for item in json_lines(
        run_cli(path, command, "--target", "fan").stdout
    )] == ["a1", "a3"]
    assert json_lines(run_cli(path, command, "--target", "风扇").stdout)[0]["action_id"] == "a4"
    assert len(json_lines(run_cli(path, command, "--limit", "2").stdout)) == 2
    assert run_cli(path, command, "--target", "missing").stdout == ""
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before


@pytest.mark.parametrize("command", ["list", "list-dead"])
@pytest.mark.parametrize("limit", ["0", "-1", "1.5"])
def test_cli_list_invalid_limit_creates_no_files(tmp_path, command, limit):
    path = tmp_path / "missing" / "queue.jsonl"
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, command, "--limit", limit)
    assert result.value.stdout == ""
    assert "limit" in result.value.stderr
    assert "Traceback" not in result.value.stderr
    assert not path.parent.exists()


def test_cli_requeue_supports_scheduled_recovery(tmp_path):
    path = tmp_path / "queue.jsonl"
    run_cli(path, "enqueue", "fan", "set", "1", "--id", "old")
    run_cli(path, "run-demo", "--fail-target", "fan", "--max-attempts", "1")
    before = path.read_bytes()
    for invalid in ("bad", "2999-01-01T00:00:00"):
        with pytest.raises(subprocess.CalledProcessError) as result:
            run_cli(path, "requeue", "old", "--not-before", invalid)
        assert "not-before" in result.value.stderr
        assert path.read_bytes() == before
    run_cli(path, "requeue", "old", "--new-id", "new",
            "--not-before", "2999-01-01T08:00:00+08:00")
    [pending] = json_lines(run_cli(path, "list").stdout)
    assert pending["action_id"] == "new"
    assert pending["next_attempt_at"] == "2999-01-01T00:00:00+00:00"
    [report] = json_lines(run_cli(path, "run-demo").stdout)
    assert report["deferred"] == ["new"]
    assert report["processed"] == 0
    assert json_lines(run_cli(path, "list-dead").stdout)[0]["action_id"] == "old"


@pytest.mark.parametrize("value", [
    '{"enabled": false, "enabled": true}',
    '{"device": {"speed": 0, "speed": 1}}',
    '[{"speed": 0, "speed": 1}]',
    r'{"a": 1, "\u0061": 2}',
])
def test_cli_duplicate_json_keys_are_rejected_without_mutation(tmp_path, value):
    path = tmp_path / "queue.jsonl"
    run_cli(path, "enqueue", "fan", "set", "0", "--id", "existing")
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, "enqueue", "fan", "set", value)
    assert result.value.returncode == 1
    assert result.value.stdout == ""
    assert "duplicate JSON keys" in result.value.stderr
    assert "Traceback" not in result.value.stderr
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before


@pytest.mark.parametrize("value", ['NaN', 'Infinity', '[1e999]', '{"speed": -Infinity}'])
def test_cli_non_finite_json_value_creates_no_queue(tmp_path, value):
    path = tmp_path / "queue.jsonl"
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, "enqueue", "fan", "set", value)
    assert result.value.stdout == ""
    assert "Traceback" not in result.value.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_same_key_in_separate_objects_is_valid(tmp_path):
    path = tmp_path / "queue.jsonl"
    value = '[{"speed": 0}, {"speed": 1}, {"name": "风扇"}]'
    run_cli(path, "enqueue", "fan", "set", value)
    [item] = json_lines(run_cli(path, "list").stdout)
    assert item["value"] == json.loads(value)


def test_cli_status_empty_queue_creates_no_files(tmp_path):
    path = tmp_path / "missing" / "queue.jsonl"
    [status] = json_lines(run_cli(path, "status", "--fail-on-dead").stdout)
    assert status == {
        "pending": 0, "ready": 0, "deferred": 0, "leased": 0,
        "dead_letters": 0, "next_ready_at": None,
    }
    assert not path.parent.exists()


def test_cli_status_reports_actual_queue_without_modifying_files(tmp_path):
    path = tmp_path / "queue.jsonl"
    audit = AuditLog(path)
    queue = DurableActionQueue(audit)
    now = datetime.now(timezone.utc)
    future = datetime(2999, 1, 1, tzinfo=timezone.utc)
    queue.enqueue(Action("fan", "set", 1, "dead"), action_id="dead", now=now)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                   max_attempts=1, now=now)
    queue.enqueue(Action("fan", "set", 1, "ready"), action_id="ready", now=now)
    queue.enqueue(Action("fan", "set", 1, "scheduled"), action_id="scheduled",
                  now=now, not_before=future)
    queue.enqueue(Action("fan", "set", 1, "leased"), action_id="leased", now=now)
    audit.append("queued_action_attempted", "fan", {
        "action_id": "leased", "lease_expires_at": (future + timedelta(days=1)).isoformat(),
    }, timestamp=now)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    [status] = json_lines(run_cli(path, "status").stdout)
    assert status == {
        "pending": 3, "ready": 1, "deferred": 1, "leased": 1,
        "dead_letters": 1, "next_ready_at": future.isoformat(),
    }
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, "status", "--fail-on-dead")
    assert result.value.returncode == 1
    assert json_lines(result.value.stdout) == [status]
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before


def test_cli_status_corrupt_queue_fails_without_claiming_healthy(tmp_path):
    path = tmp_path / "queue.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, "status")
    assert result.value.stdout == ""
    assert "队列操作失败" in result.value.stderr
    assert "Traceback" not in result.value.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("arguments", [
    ("run-demo", "--max-attempts", "0"),
    ("run-demo", "--retry-delay", "nan"),
    ("run-demo", "--lease-seconds", "inf"),
    ("enqueue", "fan", "set", "1", "--id", "bad/id"),
])
def test_cli_invalid_input_has_concise_error_without_writes(tmp_path, arguments):
    path = tmp_path / "queue.jsonl"
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, *arguments)
    assert result.value.returncode == 1
    assert result.value.stdout == ""
    assert "队列操作失败" in result.value.stderr
    assert "Traceback" not in result.value.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_storage_failure_has_concise_error(tmp_path):
    path = tmp_path / "not-a-file"
    path.mkdir()
    with pytest.raises(subprocess.CalledProcessError) as result:
        run_cli(path, "status")
    assert result.value.returncode == 1
    assert result.value.stdout == ""
    assert "队列操作失败" in result.value.stderr
    assert "Traceback" not in result.value.stderr
    assert path.is_dir()
    assert list(path.iterdir()) == []


def test_cli_schedule_is_persisted_and_deferred(tmp_path):
    queue = tmp_path / "queue.jsonl"
    run_cli(queue, "enqueue", "fan", "set", "1", "--id", "scheduled",
            "--not-before", "2999-01-01T08:00:00+08:00")
    [item] = json_lines(run_cli(queue, "list").stdout)
    assert item["next_attempt_at"] == "2999-01-01T00:00:00+00:00"
    [report] = json_lines(run_cli(queue, "run-demo").stdout)
    assert report["processed"] == 0
    assert report["deferred"] == ["scheduled"]


def test_cli_rejects_schedule_without_timezone(tmp_path):
    queue = tmp_path / "queue.jsonl"
    try:
        run_cli(queue, "enqueue", "fan", "set", "1", "--not-before", "2026-09-02T12:00:00")
    except subprocess.CalledProcessError as error:
        assert "not-before" in error.stderr
        assert not queue.exists()
    else:
        raise AssertionError("invalid schedule accepted")


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
