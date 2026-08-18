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
