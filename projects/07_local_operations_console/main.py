from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action, Event, Rule, RuleEngine
from rpi_mastery.energy import EnergyWindow, FlexibleLoad
from rpi_mastery.health import DeviceHealthMonitor
from rpi_mastery.operations import LocalOperations, render_snapshot


def is_active_leak(event: Event) -> bool:
    if not isinstance(event.value, bool):
        raise TypeError("water_leak 事件的 value 必须是布尔值")
    return event.value


def build_console(audit_path: Path) -> LocalOperations:
    engine = RuleEngine(
        [
            Rule(
                "high-temperature",
                "temperature_c",
                lambda event: float(event.value) >= 30,
                lambda event: Action(
                    "fan",
                    "on",
                    True,
                    f"室温 {event.value}°C，已超过 30°C",
                ),
            ),
            Rule(
                "water-leak",
                "water_leak",
                is_active_leak,
                lambda event: Action(
                    "water-valve",
                    "close",
                    True,
                    "检测到漏水",
                ),
            ),
        ]
    )
    return LocalOperations(engine, DeviceHealthMonitor(), AuditLog(audit_path))


def load_demo(console: LocalOperations, now: datetime) -> None:
    console.record_heartbeat(
        "living-room-sensor",
        expected_interval=timedelta(seconds=30),
        seen_at=now - timedelta(seconds=12),
    )
    console.record_heartbeat(
        "water-valve",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=now - timedelta(seconds=75),
    )
    console.process(Event("temperature_c", 31.2, "living-room-sensor", now))
    console.plan_energy(
        [
            FlexibleLoad("热水器", power_kw=2.0, duration_hours=1.0, priority=3),
            FlexibleLoad("洗衣机", power_kw=0.8, duration_hours=1.5, priority=2),
        ],
        [
            EnergyWindow(
                "中午光伏",
                0.55,
                solar_surplus_kw=1.0,
                capacity_kw=1.5,
                duration_hours=4.0,
            ),
            EnergyWindow(
                "夜间低谷",
                0.35,
                solar_surplus_kw=0.0,
                capacity_kw=1.5,
                duration_hours=8.0,
            ),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="树莓派本地运行状态控制台")
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=Path("data/operations.jsonl"),
        help="本地审计日志路径",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    parser.add_argument("--ack", metavar="CODE", help="确认一个活动告警")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    console = build_console(args.audit_log)
    load_demo(console, now)
    console.snapshot(now=now)
    if args.ack:
        try:
            console.acknowledge_alert(args.ack, now=now)
        except KeyError as error:
            raise SystemExit(error.args[0]) from error

    snapshot = console.snapshot(now=now)
    if args.json:
        print(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_snapshot(snapshot))


if __name__ == "__main__":
    main()
