from datetime import datetime, timedelta, timezone

from rpi_mastery.health import DeviceHealthMonitor, DeviceStatus

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def test_critical_offline_device_requests_safe_state():
    monitor = DeviceHealthMonitor()
    monitor.record(
        "water-valve",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=NOW - timedelta(seconds=61),
    )

    report = monitor.inspect("water-valve", now=NOW)

    assert report.status is DeviceStatus.OFFLINE
    assert report.requires_safe_state


def test_late_device_does_not_trigger_safe_state():
    monitor = DeviceHealthMonitor()
    monitor.record(
        "temperature-sensor",
        expected_interval=timedelta(seconds=30),
        seen_at=NOW - timedelta(seconds=45),
    )

    report = monitor.inspect("temperature-sensor", now=NOW)

    assert report.status is DeviceStatus.LATE
    assert not report.requires_safe_state


def test_unknown_device_has_clear_status():
    report = DeviceHealthMonitor().inspect("missing", now=NOW)

    assert report.status is DeviceStatus.UNKNOWN
    assert report.age_seconds is None


def test_naive_datetimes_are_treated_as_utc():
    monitor = DeviceHealthMonitor()
    monitor.record(
        "indoor-sensor",
        expected_interval=timedelta(seconds=30),
        seen_at=(NOW - timedelta(seconds=15)).replace(tzinfo=None),
    )

    report = monitor.inspect(
        "indoor-sensor",
        now=NOW.replace(tzinfo=None),
    )

    assert report.status is DeviceStatus.ONLINE
    assert report.age_seconds == 15


def test_older_heartbeat_does_not_replace_newer_reading():
    monitor = DeviceHealthMonitor()
    monitor.record(
        "water-valve",
        expected_interval=timedelta(seconds=30),
        seen_at=NOW - timedelta(seconds=10),
    )
    monitor.record(
        "water-valve",
        expected_interval=timedelta(seconds=5),
        critical=True,
        seen_at=NOW - timedelta(minutes=2),
    )

    report = monitor.inspect("water-valve", now=NOW)

    assert report.status is DeviceStatus.ONLINE
    assert report.age_seconds == 10
    assert not report.requires_safe_state
