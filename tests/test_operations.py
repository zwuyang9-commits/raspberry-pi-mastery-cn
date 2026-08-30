from datetime import datetime, timedelta, timezone

import pytest

from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action, Event, Rule, RuleEngine
from rpi_mastery.energy import EnergyWindow, FlexibleLoad
from rpi_mastery.health import DeviceHealthMonitor
from rpi_mastery.operations import (
    AlertSeverity,
    AlertState,
    LocalOperations,
    render_prometheus,
    render_snapshot,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def build_operations(tmp_path) -> LocalOperations:
    engine = RuleEngine(
        [
            Rule(
                "hot",
                "temperature_c",
                lambda event: event.value >= 30,
                lambda event: Action("fan", "on", True, "室温超过 30°C"),
            )
        ]
    )
    return LocalOperations(
        engine,
        DeviceHealthMonitor(),
        AuditLog(tmp_path / "hub.jsonl"),
    )


def test_snapshot_joins_health_energy_actions_and_alerts(tmp_path):
    operations = build_operations(tmp_path)
    operations.record_heartbeat(
        "water-valve",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=NOW - timedelta(seconds=61),
    )
    operations.process(Event("temperature_c", 31, "living-room", NOW))
    operations.plan_energy(
        [FlexibleLoad("heater", power_kw=2.0, duration_hours=1.0)],
        [EnergyWindow("small", 0.2, solar_surplus_kw=0.0, capacity_kw=0.5)],
    )

    snapshot = operations.snapshot(now=NOW)

    assert snapshot.status == "critical"
    assert snapshot.recent_actions[0].source == "fan"
    assert snapshot.energy[0].window == "未安排"
    assert [alert.code for alert in snapshot.alerts] == [
        "device:water-valve",
        "energy:heater",
    ]
    assert snapshot.alerts[0].severity is AlertSeverity.CRITICAL

    data = snapshot.as_dict()
    assert data["health"][0]["requires_safe_state"] is True
    assert data["recent_actions"][0]["event_source"] == "living-room"
    assert "water-valve" in render_snapshot(snapshot)


def test_acknowledgement_survives_snapshots_and_resets_after_recovery(tmp_path):
    operations = build_operations(tmp_path)
    operations.record_heartbeat(
        "sensor",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=NOW - timedelta(seconds=45),
    )
    operations.snapshot(now=NOW)

    acknowledged = operations.acknowledge_alert("device:sensor", now=NOW)
    assert acknowledged.state is AlertState.ACKNOWLEDGED
    assert operations.snapshot(now=NOW).alerts[0].state is AlertState.ACKNOWLEDGED

    operations.record_heartbeat(
        "sensor",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=NOW,
    )
    assert operations.snapshot(now=NOW).alerts == ()

    operations.record_heartbeat(
        "sensor",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=NOW + timedelta(seconds=1),
    )
    reopened = operations.snapshot(now=NOW + timedelta(seconds=62)).alerts[0]
    assert reopened.state is AlertState.OPEN
    assert reopened.severity is AlertSeverity.CRITICAL


def test_snapshot_rejects_invalid_recent_action_limit(tmp_path):
    operations = build_operations(tmp_path)

    with pytest.raises(ValueError, match="positive"):
        operations.snapshot(now=NOW, recent_action_limit=0)


def test_prometheus_export_contains_health_alert_energy_and_actions(tmp_path):
    operations = build_operations(tmp_path)
    operations.record_heartbeat(
        'sensor"north',
        expected_interval=timedelta(seconds=30),
        seen_at=NOW - timedelta(seconds=61),
    )
    operations.process(Event("temperature_c", 31, "living-room", NOW))
    operations.plan_energy(
        [FlexibleLoad("heater", power_kw=2.0, duration_hours=1.0)],
        [EnergyWindow("night", 0.2, solar_surplus_kw=0.0, capacity_kw=2.0)],
    )

    metrics = render_prometheus(operations.snapshot(now=NOW))

    assert 'rpi_hub_status{status="warning"} 1' in metrics
    assert 'device_id="sensor\\"north",status="offline"' in metrics
    assert 'rpi_alerts{severity="warning",state="open"} 1' in metrics
    assert 'rpi_energy_estimated_cost{load="heater",window="night"} 0.4' in metrics
    assert "rpi_recent_actions 1" in metrics
    assert metrics.endswith("\n")
