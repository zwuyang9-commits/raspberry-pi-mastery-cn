from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from rpi_mastery.automation import Action, Event, Rule, RuleEngine
from rpi_mastery.health import DeviceHealthMonitor


def build_engine() -> RuleEngine:
    return RuleEngine(
        [
            Rule(
                "high-temperature",
                "temperature_c",
                lambda event: float(event.value) >= 30,
                lambda event: Action("fan", "set", 1, f"温度 {event.value}°C 达到阈值"),
            ),
            Rule(
                "poor-air-quality",
                "air_quality_index",
                lambda event: int(event.value) >= 150,
                lambda event: Action("ventilation", "set", 1, f"AQI {event.value} 需要通风"),
            ),
            Rule(
                "water-leak",
                "water_leak",
                lambda event: bool(event.value),
                lambda event: Action("water_valve", "close", True, "检测到漏水，进入安全状态"),
            ),
        ]
    )


def run_demo() -> None:
    engine = build_engine()
    events = [
        Event.now("temperature_c", 31.2, "living-room"),
        Event.now("air_quality_index", 173, "bedroom"),
        Event.now("water_leak", True, "utility-room"),
    ]
    for event in events:
        for action in engine.evaluate(event):
            print(json.dumps(action.__dict__, ensure_ascii=False))

    monitor = DeviceHealthMonitor()
    now = datetime.now(timezone.utc)
    monitor.record(
        "water-valve",
        expected_interval=timedelta(seconds=30),
        critical=True,
        seen_at=now - timedelta(seconds=75),
    )
    for report in monitor.inspect_all(now=now):
        print(
            json.dumps(
                {
                    "device": report.device_id,
                    "status": report.status.value,
                    "message": report.message,
                    "requires_safe_state": report.requires_safe_state,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="离线优先的韧性家庭智能中枢")
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    if not args.simulate:
        raise SystemExit("当前版本请使用 --simulate；真实设备适配见 README")
    run_demo()
