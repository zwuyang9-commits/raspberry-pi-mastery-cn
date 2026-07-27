from __future__ import annotations

import argparse
import csv
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Reading:
    temperature_c: float
    humidity_pct: float


class SimulatedSensor:
    def __init__(self) -> None:
        self.index = 0

    def read(self) -> Reading:
        value = Reading(22 + math.sin(self.index / 5), 50 + 4 * math.cos(self.index / 7))
        self.index += 1
        return value


def collect(sensor, samples: int, interval: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_utc", "temperature_c", "humidity_pct"])
        for _ in range(samples):
            reading = sensor.read()
            writer.writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    f"{reading.temperature_c:.2f}",
                    f"{reading.humidity_pct:.2f}",
                ]
            )
            handle.flush()
            time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="智能环境站")
    parser.add_argument("--simulate", action="store_true", help="当前示例必须显式选择模拟模式")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("data/environment.csv"))
    args = parser.parse_args()
    if not args.simulate:
        raise SystemExit("请添加 --simulate，或按 README 实现真实传感器适配器")
    collect(SimulatedSensor(), args.samples, args.interval, args.output)
