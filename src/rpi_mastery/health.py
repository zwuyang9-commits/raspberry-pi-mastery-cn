"""Device heartbeat monitoring for an offline-first Raspberry Pi hub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class DeviceStatus(str, Enum):
    ONLINE = "online"
    LATE = "late"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeviceHeartbeat:
    device_id: str
    seen_at: datetime
    expected_interval: timedelta
    critical: bool = False


@dataclass(frozen=True)
class HealthReport:
    device_id: str
    status: DeviceStatus
    age_seconds: float | None
    message: str
    requires_safe_state: bool


class DeviceHealthMonitor:
    """Tracks device heartbeats without relying on cloud connectivity."""

    def __init__(self) -> None:
        self._heartbeats: dict[str, DeviceHeartbeat] = {}

    def record(
        self,
        device_id: str,
        *,
        expected_interval: timedelta,
        critical: bool = False,
        seen_at: datetime | None = None,
    ) -> None:
        if expected_interval.total_seconds() <= 0:
            raise ValueError("expected_interval must be positive")
        self._heartbeats[device_id] = DeviceHeartbeat(
            device_id=device_id,
            seen_at=seen_at or datetime.now(timezone.utc),
            expected_interval=expected_interval,
            critical=critical,
        )

    def inspect(
        self,
        device_id: str,
        *,
        now: datetime | None = None,
    ) -> HealthReport:
        heartbeat = self._heartbeats.get(device_id)
        if heartbeat is None:
            return HealthReport(
                device_id,
                DeviceStatus.UNKNOWN,
                None,
                "还没有收到这个设备的心跳",
                False,
            )

        current_time = now or datetime.now(timezone.utc)
        age = current_time - heartbeat.seen_at
        expected = heartbeat.expected_interval

        if age <= expected:
            status = DeviceStatus.ONLINE
            message = "设备通信正常"
        elif age <= expected * 2:
            status = DeviceStatus.LATE
            message = "心跳延迟，继续观察"
        else:
            status = DeviceStatus.OFFLINE
            message = "设备已超过两个心跳周期没有响应"

        return HealthReport(
            heartbeat.device_id,
            status,
            max(0.0, age.total_seconds()),
            message,
            heartbeat.critical and status is DeviceStatus.OFFLINE,
        )

    def inspect_all(self, *, now: datetime | None = None) -> list[HealthReport]:
        return [
            self.inspect(device_id, now=now)
            for device_id in sorted(self._heartbeats)
        ]
