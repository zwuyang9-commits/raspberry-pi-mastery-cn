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
