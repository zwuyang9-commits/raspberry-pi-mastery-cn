import json
from datetime import datetime, timedelta, timezone

import pytest

from rpi_mastery.audit import AuditLog, AuditLogCorrupted

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


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
