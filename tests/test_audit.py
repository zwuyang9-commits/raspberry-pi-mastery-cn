import json
import multiprocessing
from datetime import datetime, timedelta, timezone

import pytest

import rpi_mastery.audit as audit_module
from rpi_mastery.audit import AuditLog, AuditLogCorrupted

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


def _append_audit_records(path, worker, count):
    log = AuditLog(path)
    for index in range(count):
        log.append("concurrent", worker, {"index": index}, timestamp=NOW)


def test_audit_log_appends_and_filters_records(tmp_path):
    log = AuditLog(tmp_path / "hub.jsonl")
    log.append("event", "kitchen", {"temperature": 23.5}, timestamp=NOW)
    log.append(
        "action",
        "fan",
        {"command": "off"},
        timestamp=NOW + timedelta(seconds=1),
    )

    actions = log.read(kind="action")

    assert len(actions) == 1
    assert actions[0].source == "fan"
    assert actions[0].payload == {"command": "off"}


def test_audit_log_returns_latest_records(tmp_path):
    log = AuditLog(tmp_path / "hub.jsonl")
    for index in range(3):
        log.append("event", "sensor", {"index": index}, timestamp=NOW)

    entries = log.read(limit=2)

    assert [entry.payload["index"] for entry in entries] == [1, 2]


def test_audit_log_reports_corrupted_line(tmp_path):
    path = tmp_path / "hub.jsonl"
    path.write_text('{"kind":"event"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(AuditLogCorrupted) as error:
        AuditLog(path).read()

    assert error.value.line_number == 1


def test_audit_log_normalizes_naive_timestamps_to_utc(tmp_path):
    log = AuditLog(tmp_path / "hub.jsonl")
    naive_timestamp = NOW.replace(tzinfo=None)

    written = log.append("event", "sensor", {}, timestamp=naive_timestamp)
    [loaded] = log.read(since=NOW)

    assert written.timestamp == NOW
    assert written.timestamp.tzinfo is timezone.utc
    assert loaded.timestamp == NOW
    assert loaded.timestamp.tzinfo is timezone.utc


def test_audit_log_normalizes_offset_timestamps_before_filtering(tmp_path):
    path = tmp_path / "hub.jsonl"
    record = {
        "timestamp": "2026-07-30T16:00:00+08:00",
        "kind": "event",
        "source": "sensor",
        "payload": {"online": True},
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    entries = AuditLog(path).read(since=NOW.replace(tzinfo=None))

    assert len(entries) == 1
    assert entries[0].timestamp == NOW
    assert entries[0].timestamp.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "record",
    [
        [],
        {
            "timestamp": "2026-07-30T08:00:00+00:00",
            "kind": "event",
            "source": "sensor",
            "payload": [["online", True]],
        },
        {
            "timestamp": "2026-07-30T08:00:00+00:00",
            "kind": "event",
            "source": "sensor",
            "payload": None,
        },
    ],
)
def test_audit_log_rejects_non_object_records_and_payloads(tmp_path, record):
    path = tmp_path / "hub.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(AuditLogCorrupted) as error:
        AuditLog(path).read()

    assert error.value.line_number == 1


def test_audit_log_rejects_non_dictionary_payloads_on_append(tmp_path):
    log = AuditLog(tmp_path / "hub.jsonl")

    with pytest.raises(TypeError, match="payload must be a dictionary"):
        log.append("event", "sensor", [("online", True)])  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_audit_log_rejects_non_standard_payload_before_creating_log(tmp_path, value):
    path = tmp_path / "hub.jsonl"
    log = AuditLog(path)

    with pytest.raises(ValueError, match="JSON-serializable finite"):
        log.append("event", "sensor", {"value": value}, timestamp=NOW)

    assert not path.exists()
    assert not log._lock_path.exists()


def test_audit_log_treats_non_standard_json_number_as_corruption(tmp_path):
    path = tmp_path / "hub.jsonl"
    path.write_text(
        '{"timestamp":"2026-07-30T08:00:00+00:00","kind":"event",'
        '"source":"sensor","payload":{"value":NaN}}\n',
        encoding="utf-8",
    )

    with pytest.raises(AuditLogCorrupted) as error:
        AuditLog(path).read()

    assert error.value.line_number == 1


@pytest.mark.parametrize(
    "record",
    [
        (
            '{"timestamp":"2026-07-30T08:00:00+00:00","kind":"event",'
            '"kind":"action","source":"sensor","payload":{}}'
        ),
        (
            '{"timestamp":"2026-07-30T08:00:00+00:00","kind":"event",'
            '"source":"sensor","payload":{"value":1,"value":2}}'
        ),
    ],
)
def test_audit_log_treats_duplicate_json_keys_as_corruption(tmp_path, record):
    path = tmp_path / "hub.jsonl"
    path.write_text(record + "\n", encoding="utf-8")

    with pytest.raises(AuditLogCorrupted) as error:
        AuditLog(path).read()

    assert error.value.line_number == 1


def test_read_filters_by_source_and_closed_time_range(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("event", "sensor-a", {"value": 1}, timestamp=NOW)
    log.append("event", "sensor-b", {"value": 2}, timestamp=NOW + timedelta(minutes=1))
    log.append("action", "sensor-a", {"value": 3}, timestamp=NOW + timedelta(minutes=2))

    entries = log.read(
        source="sensor-a",
        since=NOW,
        until=NOW + timedelta(minutes=1),
    )

    assert [entry.payload["value"] for entry in entries] == [1]


def test_summary_counts_filtered_kinds_and_sources(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("event", "sensor-a", {}, timestamp=NOW)
    log.append("event", "sensor-b", {}, timestamp=NOW + timedelta(minutes=1))
    log.append("action", "fan", {}, timestamp=NOW + timedelta(minutes=2))

    summary = log.summarize(since=NOW + timedelta(seconds=30))

    assert summary.entries == 2
    assert summary.kinds == {"action": 1, "event": 1}
    assert summary.sources == {"fan": 1, "sensor-b": 1}
    assert summary.first_timestamp == NOW + timedelta(minutes=1)
    assert summary.last_timestamp == NOW + timedelta(minutes=2)


def test_read_rejects_reversed_time_range(tmp_path):
    with pytest.raises(ValueError, match="since cannot"):
        AuditLog(tmp_path / "audit.jsonl").read(
            since=NOW + timedelta(seconds=1),
            until=NOW,
        )


def test_archive_preview_does_not_modify_files(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("event", "old", {}, timestamp=NOW)
    log.append("event", "new", {}, timestamp=NOW + timedelta(days=1))
    before = path.read_bytes()

    report = log.archive_before(
        NOW + timedelta(hours=1),
        tmp_path / "archive.jsonl",
    )

    assert report.archived_entries == 1
    assert report.retained_entries == 1
    assert report.applied is False
    assert path.read_bytes() == before
    assert not report.archive.exists()


def test_archive_apply_moves_old_records_and_preserves_cutoff_boundary(tmp_path):
    path = tmp_path / "audit.jsonl"
    archive = tmp_path / "archives" / "old.jsonl"
    log = AuditLog(path)
    log.append("event", "old", {}, timestamp=NOW)
    log.append("event", "boundary", {}, timestamp=NOW + timedelta(hours=1))
    log.append("event", "new", {}, timestamp=NOW + timedelta(hours=2))

    report = log.archive_before(NOW + timedelta(hours=1), archive, apply=True)

    assert report.applied is True
    assert [entry.source for entry in AuditLog(archive).read()] == ["old"]
    assert [entry.source for entry in log.read()] == ["boundary", "new"]


def test_archive_refuses_to_overwrite_existing_file(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("event", "old", {}, timestamp=NOW)
    archive = tmp_path / "archive.jsonl"
    archive.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        log.archive_before(NOW + timedelta(seconds=1), archive, apply=True)

    assert [entry.source for entry in log.read()] == ["old"]
    assert archive.read_text(encoding="utf-8") == "keep"


def test_archive_rolls_back_published_copy_when_source_replace_fails(
    tmp_path, monkeypatch
):
    path = tmp_path / "audit.jsonl"
    archive = tmp_path / "archive.jsonl"
    log = AuditLog(path)
    log.append("event", "old", {}, timestamp=NOW)
    log.append("event", "new", {}, timestamp=NOW + timedelta(days=1))
    before = path.read_bytes()
    real_replace = audit_module.os.replace

    def fail_source_replace(source, destination):
        if destination == path.resolve():
            raise OSError("simulated source replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(audit_module.os, "replace", fail_source_replace)

    with pytest.raises(OSError, match="simulated source replacement failure"):
        log.archive_before(NOW + timedelta(hours=1), archive, apply=True)

    assert path.read_bytes() == before
    assert not archive.exists()


def test_concurrent_processes_append_complete_jsonl_records(tmp_path):
    path = tmp_path / "shared.jsonl"
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_append_audit_records, args=(path, f"worker-{index}", 25))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)

    assert [worker.exitcode for worker in workers] == [0, 0, 0, 0]
    entries = AuditLog(path).read(kind="concurrent")
    assert len(entries) == 100
    assert {entry.source for entry in entries} == {
        "worker-0",
        "worker-1",
        "worker-2",
        "worker-3",
    }


def test_generic_archive_refuses_to_split_queue_lifecycle(tmp_path):
    path = tmp_path / "queue.jsonl"
    archive = tmp_path / "archive.jsonl"
    log = AuditLog(path)
    log.append(
        "queued_action_created",
        "fan",
        {"action_id": "keep-together"},
        timestamp=NOW,
    )
    before = path.read_bytes()

    with pytest.raises(ValueError, match="queue lifecycle"):
        log.archive_before(NOW + timedelta(seconds=1), archive, apply=True)

    assert path.read_bytes() == before
    assert not archive.exists()
