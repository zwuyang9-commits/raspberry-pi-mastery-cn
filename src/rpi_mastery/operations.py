"""Local operations console that joins health, automation, energy and audit data."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .audit import AuditEntry, AuditLog
from .automation import Action, Event, RuleEngine
from .energy import EnergyScheduler, EnergyWindow, FlexibleLoad, ScheduleDecision
from .health import DeviceHealthMonitor, DeviceStatus, HealthReport


class AlertSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True)
class Alert:
    """An active local alert reconstructed from the append-only audit log."""

    code: str
    severity: AlertSeverity
    source: str
    message: str
    state: AlertState
    opened_at: datetime
    acknowledged_at: datetime | None = None


@dataclass(frozen=True)
class HealthTrend:
    """Availability summary reconstructed from periodic local health samples."""

    device_id: str
    samples: int
    online_samples: int
    availability_percent: float
    offline_transitions: int


@dataclass(frozen=True)
class _AlertCandidate:
    code: str
    severity: AlertSeverity
    source: str
    message: str


class AlertManager:
    """Keeps alert acknowledgements durable without requiring a database."""

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def sync(
        self,
        candidates: list[_AlertCandidate],
        *,
        now: datetime | None = None,
    ) -> tuple[Alert, ...]:
        """Open, update and resolve alerts to match current conditions."""

        timestamp = now or datetime.now(timezone.utc)
        active = self._active_alerts()
        wanted = {candidate.code: candidate for candidate in candidates}

        for code in sorted(active.keys() - wanted.keys()):
            self.audit.append(
                "alert_resolved",
                active[code].source,
                {"code": code},
                timestamp=timestamp,
            )

        for code in sorted(wanted):
            candidate = wanted[code]
            current = active.get(code)
            changed = current is not None and (
                current.severity is not candidate.severity
                or current.source != candidate.source
                or current.message != candidate.message
            )
            if current is None or changed:
                self.audit.append(
                    "alert_opened",
                    candidate.source,
                    {
                        "code": candidate.code,
                        "severity": candidate.severity.value,
                        "message": candidate.message,
                    },
                    timestamp=timestamp,
                )

        return self._sorted(self._active_alerts())

    def acknowledge(
        self,
        code: str,
        *,
        now: datetime | None = None,
    ) -> Alert:
        active = self._active_alerts()
        alert = active.get(code)
        if alert is None:
            raise KeyError(f"没有活动告警: {code}")
        if alert.state is AlertState.ACKNOWLEDGED:
            return alert

        timestamp = now or datetime.now(timezone.utc)
        self.audit.append(
            "alert_acknowledged",
            alert.source,
            {"code": code},
            timestamp=timestamp,
        )
        return replace(
            alert,
            state=AlertState.ACKNOWLEDGED,
            acknowledged_at=timestamp,
        )

    def _active_alerts(self) -> dict[str, Alert]:
        active: dict[str, Alert] = {}
        for entry in self.audit.read():
            code = entry.payload.get("code")
            if not isinstance(code, str) or not code:
                continue
            if entry.kind == "alert_opened":
                try:
                    severity = AlertSeverity(entry.payload["severity"])
                    message = str(entry.payload["message"])
                except (KeyError, ValueError):
                    continue
                active[code] = Alert(
                    code=code,
                    severity=severity,
                    source=entry.source,
                    message=message,
                    state=AlertState.OPEN,
                    opened_at=entry.timestamp,
                )
            elif entry.kind == "alert_acknowledged" and code in active:
                active[code] = replace(
                    active[code],
                    state=AlertState.ACKNOWLEDGED,
                    acknowledged_at=entry.timestamp,
                )
            elif entry.kind == "alert_resolved":
                active.pop(code, None)
        return active

    @staticmethod
    def _sorted(alerts: dict[str, Alert]) -> tuple[Alert, ...]:
        rank = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1}
        return tuple(sorted(alerts.values(), key=lambda alert: (rank[alert.severity], alert.code)))


@dataclass(frozen=True)
class HubSnapshot:
    """A point-in-time view suitable for a terminal, API or status page."""

    generated_at: datetime
    health: tuple[HealthReport, ...]
    energy: tuple[ScheduleDecision, ...]
    recent_actions: tuple[AuditEntry, ...]
    alerts: tuple[Alert, ...]
    health_trends: tuple[HealthTrend, ...]

    @property
    def status(self) -> str:
        severities = {alert.severity for alert in self.alerts}
        if AlertSeverity.CRITICAL in severities:
            return "critical"
        if AlertSeverity.WARNING in severities:
            return "warning"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "health": [
                {
                    "device_id": report.device_id,
                    "status": report.status.value,
                    "age_seconds": report.age_seconds,
                    "message": report.message,
                    "requires_safe_state": report.requires_safe_state,
                }
                for report in self.health
            ],
            "health_trends": [
                {
                    "device_id": trend.device_id,
                    "samples": trend.samples,
                    "online_samples": trend.online_samples,
                    "availability_percent": trend.availability_percent,
                    "offline_transitions": trend.offline_transitions,
                }
                for trend in self.health_trends
            ],
            "energy": [
                {
                    "load": decision.load,
                    "window": decision.window,
                    "estimated_cost": decision.estimated_cost,
                    "reason": decision.reason,
                }
                for decision in self.energy
            ],
            "recent_actions": [
                {
                    **entry.payload,
                    "timestamp": entry.timestamp.isoformat(),
                    "target": entry.source,
                }
                for entry in self.recent_actions
            ],
            "alerts": [
                {
                    "code": alert.code,
                    "severity": alert.severity.value,
                    "source": alert.source,
                    "message": alert.message,
                    "state": alert.state.value,
                    "opened_at": alert.opened_at.isoformat(),
                    "acknowledged_at": (
                        alert.acknowledged_at.isoformat()
                        if alert.acknowledged_at is not None
                        else None
                    ),
                }
                for alert in self.alerts
            ],
        }


class LocalOperations:
    """Coordinates the core services used by an offline Raspberry Pi hub."""

    def __init__(
        self,
        engine: RuleEngine,
        monitor: DeviceHealthMonitor,
        audit: AuditLog,
        *,
        scheduler: EnergyScheduler | None = None,
    ) -> None:
        self.engine = engine
        self.monitor = monitor
        self.audit = audit
        self.scheduler = scheduler or EnergyScheduler()
        self.alerts = AlertManager(audit)
        self._energy_decisions: tuple[ScheduleDecision, ...] = ()

    def record_heartbeat(
        self,
        device_id: str,
        *,
        expected_interval: timedelta,
        critical: bool = False,
        seen_at: datetime | None = None,
    ) -> None:
        self.monitor.record(
            device_id,
            expected_interval=expected_interval,
            critical=critical,
            seen_at=seen_at,
        )

    def process(self, event: Event) -> list[Action]:
        self.audit.append(
            "event",
            event.source,
            {"name": event.kind, "value": event.value},
            timestamp=event.timestamp,
        )
        actions = self.engine.evaluate(event)
        for action in actions:
            self.audit.append(
                "action",
                action.target,
                {
                    "command": action.command,
                    "value": action.value,
                    "reason": action.reason,
                    "event_kind": event.kind,
                    "event_source": event.source,
                },
            )
        return actions

    def plan_energy(
        self,
        loads: list[FlexibleLoad],
        windows: list[EnergyWindow],
    ) -> list[ScheduleDecision]:
        decisions = self.scheduler.schedule(loads, windows)
        self._energy_decisions = tuple(decisions)
        for decision in decisions:
            self.audit.append(
                "energy_decision",
                decision.load,
                {
                    "window": decision.window,
                    "estimated_cost": decision.estimated_cost,
                    "reason": decision.reason,
                },
            )
        return decisions

    def snapshot(
        self,
        *,
        now: datetime | None = None,
        recent_action_limit: int = 5,
        health_history_window: timedelta = timedelta(hours=24),
    ) -> HubSnapshot:
        if recent_action_limit < 1:
            raise ValueError("recent_action_limit must be positive")
        if health_history_window <= timedelta(0):
            raise ValueError("health_history_window must be positive")
        generated_at = now or datetime.now(timezone.utc)
        health = tuple(self.monitor.inspect_all(now=generated_at))
        for report in health:
            self.audit.append(
                "health_sample",
                report.device_id,
                {"status": report.status.value},
                timestamp=generated_at,
            )
        health_trends = self._health_trends(
            since=generated_at - health_history_window,
        )
        candidates = self._alert_candidates(health, self._energy_decisions)
        alerts = self.alerts.sync(candidates, now=generated_at)
        actions = tuple(self.audit.read(kind="action", limit=recent_action_limit))
        return HubSnapshot(
            generated_at=generated_at,
            health=health,
            energy=self._energy_decisions,
            recent_actions=actions,
            alerts=alerts,
            health_trends=health_trends,
        )

    def acknowledge_alert(self, code: str, *, now: datetime | None = None) -> Alert:
        return self.alerts.acknowledge(code, now=now)

    def _health_trends(self, *, since: datetime) -> tuple[HealthTrend, ...]:
        samples: dict[str, list[DeviceStatus]] = {}
        for entry in self.audit.read(kind="health_sample", since=since):
            try:
                status = DeviceStatus(entry.payload["status"])
            except (KeyError, ValueError):
                continue
            samples.setdefault(entry.source, []).append(status)

        trends: list[HealthTrend] = []
        unavailable = {DeviceStatus.LATE, DeviceStatus.OFFLINE}
        for device_id in sorted(samples):
            statuses = samples[device_id]
            online = sum(status is DeviceStatus.ONLINE for status in statuses)
            transitions = sum(
                status in unavailable and (index == 0 or statuses[index - 1] not in unavailable)
                for index, status in enumerate(statuses)
            )
            trends.append(
                HealthTrend(
                    device_id=device_id,
                    samples=len(statuses),
                    online_samples=online,
                    availability_percent=round(online / len(statuses) * 100, 2),
                    offline_transitions=transitions,
                )
            )
        return tuple(trends)

    @staticmethod
    def _alert_candidates(
        health: tuple[HealthReport, ...],
        decisions: tuple[ScheduleDecision, ...],
    ) -> list[_AlertCandidate]:
        candidates: list[_AlertCandidate] = []
        for report in health:
            if report.status not in {DeviceStatus.LATE, DeviceStatus.OFFLINE}:
                continue
            severity = (
                AlertSeverity.CRITICAL
                if report.requires_safe_state
                else AlertSeverity.WARNING
            )
            candidates.append(
                _AlertCandidate(
                    code=f"device:{report.device_id}",
                    severity=severity,
                    source=report.device_id,
                    message=report.message,
                )
            )
        for decision in decisions:
            if decision.window == "未安排":
                candidates.append(
                    _AlertCandidate(
                        code=f"energy:{decision.load}",
                        severity=AlertSeverity.WARNING,
                        source=decision.load,
                        message=decision.reason,
                    )
                )
        return candidates


def render_snapshot(snapshot: HubSnapshot) -> str:
    """Render a compact status page that remains readable over SSH."""

    status_labels = {"ok": "正常", "warning": "注意", "critical": "严重"}
    lines = [
        f"本地中枢状态：{status_labels[snapshot.status]}",
        f"更新时间：{snapshot.generated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "设备",
    ]
    if snapshot.health:
        for report in snapshot.health:
            age = "未知" if report.age_seconds is None else f"{report.age_seconds:.0f} 秒"
            lines.append(f"- {report.device_id}: {report.status.value}（{age}）{report.message}")
    else:
        lines.append("- 尚未登记设备")

    lines.extend(["", "能源计划"])
    if snapshot.energy:
        for decision in snapshot.energy:
            lines.append(
                f"- {decision.load}: {decision.window}，预计费用 {decision.estimated_cost:.2f} 元"
            )
    else:
        lines.append("- 尚未生成计划")

    lines.extend(["", "24 小时健康趋势"])
    if snapshot.health_trends:
        for trend in snapshot.health_trends:
            lines.append(
                f"- {trend.device_id}: 在线率 {trend.availability_percent:.2f}%，"
                f"{trend.samples} 个样本，掉线 {trend.offline_transitions} 次"
            )
    else:
        lines.append("- 暂无样本")

    lines.extend(["", "最近自动化动作"])
    if snapshot.recent_actions:
        for entry in snapshot.recent_actions:
            command = entry.payload.get("command", "未知")
            reason = entry.payload.get("reason", "")
            lines.append(f"- {entry.source}: {command}；{reason}")
    else:
        lines.append("- 暂无动作")

    lines.extend(["", "活动告警"])
    if snapshot.alerts:
        for alert in snapshot.alerts:
            lines.append(
                f"- [{alert.severity.value}/{alert.state.value}] "
                f"{alert.code}：{alert.message}"
            )
    else:
        lines.append("- 无")
    return "\n".join(lines)


def _prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_prometheus(snapshot: HubSnapshot) -> str:
    """Render a deterministic Prometheus text exposition without extra dependencies."""

    lines = [
        "# HELP rpi_hub_status Current overall hub status as a labelled gauge.",
        "# TYPE rpi_hub_status gauge",
        f'rpi_hub_status{{status="{snapshot.status}"}} 1',
        "# HELP rpi_device_health Device health state as a labelled gauge.",
        "# TYPE rpi_device_health gauge",
        "# HELP rpi_device_heartbeat_age_seconds Seconds since the latest heartbeat.",
        "# TYPE rpi_device_heartbeat_age_seconds gauge",
    ]
    for report in snapshot.health:
        device_id = _prometheus_label(report.device_id)
        status = _prometheus_label(report.status.value)
        lines.append(f'rpi_device_health{{device_id="{device_id}",status="{status}"}} 1')
        if report.age_seconds is not None:
            lines.append(f'rpi_device_heartbeat_age_seconds{{device_id="{device_id}"}} {report.age_seconds}')

    lines.extend(
        [
            "# HELP rpi_device_availability_percent Sampled availability in the history window.",
            "# TYPE rpi_device_availability_percent gauge",
            "# HELP rpi_device_offline_transitions Observed offline transitions in the history window.",
            "# TYPE rpi_device_offline_transitions gauge",
        ]
    )
    for trend in snapshot.health_trends:
        device_id = _prometheus_label(trend.device_id)
        lines.append(
            f'rpi_device_availability_percent{{device_id="{device_id}"}} '
            f"{trend.availability_percent}"
        )
        lines.append(
            f'rpi_device_offline_transitions{{device_id="{device_id}"}} '
            f"{trend.offline_transitions}"
        )

    alert_counts = {
        (severity, state): sum(
            1
            for alert in snapshot.alerts
            if alert.severity is severity and alert.state is state
        )
        for severity in AlertSeverity
        for state in AlertState
    }
    lines.extend(
        [
            "# HELP rpi_alerts Active local alerts by severity and state.",
            "# TYPE rpi_alerts gauge",
        ]
    )
    for (severity, state), count in alert_counts.items():
        lines.append(
            f'rpi_alerts{{severity="{severity.value}",state="{state.value}"}} {count}'
        )

    lines.extend(
        [
            "# HELP rpi_energy_estimated_cost Estimated scheduled cost in local currency.",
            "# TYPE rpi_energy_estimated_cost gauge",
        ]
    )
    for decision in snapshot.energy:
        load = _prometheus_label(decision.load)
        window = _prometheus_label(decision.window)
        lines.append(
            f'rpi_energy_estimated_cost{{load="{load}",window="{window}"}} '
            f"{decision.estimated_cost}"
        )
    lines.extend(
        [
            "# HELP rpi_recent_actions Number of recent actions in this snapshot.",
            "# TYPE rpi_recent_actions gauge",
            f"rpi_recent_actions {len(snapshot.recent_actions)}",
        ]
    )
    return "\n".join(lines) + "\n"
