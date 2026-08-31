"""Reusable building blocks for the Raspberry Pi mastery course."""

from .action_queue import (
    ActionQueueError,
    DispatchReport,
    DurableActionQueue,
    QueuedAction,
    QueueStatus,
)
from .audit import AuditArchiveReport, AuditEntry, AuditLog, AuditLogCorrupted, AuditSummary
from .automation import (
    Action,
    Event,
    Rule,
    RuleEngine,
    RuleEvaluation,
    RuleFailure,
)
from .backup import (
    BackupError,
    BackupFile,
    BackupReport,
    BackupRotationPlan,
    LocalBackupManager,
    RestoreDrillReport,
)
from .deployment import DeploymentCheck, DeploymentConfig, DeploymentConfigError
from .energy import EnergyScheduler, EnergyWindow, FlexibleLoad, ScheduleDecision
from .hardware import DigitalOutput, SimulatedDigitalOutput, WatchdogOutput
from .health import DeviceHealthMonitor, DeviceHeartbeat, DeviceStatus
from .operations import (
    Alert,
    AlertManager,
    AlertSeverity,
    AlertState,
    HealthTrend,
    HubSnapshot,
    LocalOperations,
    render_prometheus,
    render_snapshot,
)
from .rule_config import ReloadableRuleEngine, RuleConfigError, load_rule_engine
from .sensors import (
    BME280Sensor,
    DHT22Sensor,
    Reading,
    Sensor,
    SensorDependencyError,
    SensorReadError,
    SimulatedSensor,
    make_sensor,
)
from .vision import Detection, PrivacyFirstSentinel, SentinelEvent, SentinelStats

__version__ = "0.5.0"

__all__ = [
    "Action",
    "ActionQueueError",
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "AlertState",
    "AuditArchiveReport",
    "AuditEntry",
    "AuditLog",
    "AuditLogCorrupted",
    "AuditSummary",
    "BME280Sensor",
    "BackupError",
    "BackupFile",
    "BackupReport",
    "BackupRotationPlan",
    "DHT22Sensor",
    "DeploymentCheck",
    "DeploymentConfig",
    "DeploymentConfigError",
    "Detection",
    "DeviceHealthMonitor",
    "DeviceHeartbeat",
    "DeviceStatus",
    "DigitalOutput",
    "DispatchReport",
    "DurableActionQueue",
    "EnergyScheduler",
    "EnergyWindow",
    "Event",
    "FlexibleLoad",
    "HealthTrend",
    "HubSnapshot",
    "LocalBackupManager",
    "LocalOperations",
    "PrivacyFirstSentinel",
    "QueueStatus",
    "QueuedAction",
    "Reading",
    "ReloadableRuleEngine",
    "RestoreDrillReport",
    "Rule",
    "RuleConfigError",
    "RuleEngine",
    "RuleEvaluation",
    "RuleFailure",
    "ScheduleDecision",
    "Sensor",
    "SensorDependencyError",
    "SensorReadError",
    "SentinelEvent",
    "SentinelStats",
    "SimulatedDigitalOutput",
    "SimulatedSensor",
    "WatchdogOutput",
    "__version__",
    "load_rule_engine",
    "make_sensor",
    "render_prometheus",
    "render_snapshot",
]
