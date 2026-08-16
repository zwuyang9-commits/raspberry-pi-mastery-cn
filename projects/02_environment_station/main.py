from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from rpi_mastery.sensors import Sensor, SensorDependencyError, SensorReadError, make_sensor

CSV_HEADER = ["timestamp_utc", "temperature_c", "humidity_pct"]


def _validate_collection_options(
    *,
    samples: int,
    interval: float,
    retries: int,
    retry_delay: float,
) -> None:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("interval cannot be negative")
    if retries < 0:
        raise ValueError("retries cannot be negative")
    if not math.isfinite(retry_delay) or retry_delay < 0:
        raise ValueError("retry_delay cannot be negative")


def _read_with_retry(
    sensor: Sensor,
    *,
    retries: int,
    retry_delay: float,
    sleep: Callable[[float], None],
) -> tuple[float, float]:
    for attempt in range(retries + 1):
        try:
            reading = sensor.read()
            return reading.temperature_c, reading.humidity_pct
        except Exception as error:
            if attempt >= retries:
                raise SensorReadError(
                    f"传感器连续 {retries + 1} 次读取失败"
                ) from error
            print(
                f"读取失败（{attempt + 1}/{retries + 1}）：{error}；"
                f"{retry_delay:g} 秒后重试",
                file=sys.stderr,
            )
            sleep(retry_delay)
    raise AssertionError("unreachable")


def _needs_header(output: Path) -> bool:
    if not output.exists() or output.stat().st_size == 0:
        return True

    with output.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle), None)
    if header != CSV_HEADER:
        raise ValueError(f"现有 CSV 表头不兼容: {output}")
    return False


def collect(
    sensor: Sensor,
    *,
    samples: int,
    interval: float,
    output: Path,
    retries: int = 3,
    retry_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Append timestamped readings while preserving data from earlier runs."""

    _validate_collection_options(
        samples=samples,
        interval=interval,
        retries=retries,
        retry_delay=retry_delay,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_header = _needs_header(output)

    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(CSV_HEADER)
        for index in range(samples):
            temperature, humidity = _read_with_retry(
                sensor,
                retries=retries,
                retry_delay=retry_delay,
                sleep=sleep,
            )
            writer.writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    f"{temperature:.2f}",
                    f"{humidity:.2f}",
                ]
            )
            handle.flush()
            if index + 1 < samples:
                sleep(interval)


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负数")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须大于等于 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return parsed


def _i2c_address(value: str) -> int:
    parsed = int(value, 0)
    if parsed not in (0x76, 0x77):
        raise argparse.ArgumentTypeError("BME280 地址必须是 0x76 或 0x77")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集温湿度并追加写入 CSV")
    parser.add_argument(
        "--sensor",
        choices=("simulated", "dht22", "bme280"),
        default="simulated",
        help="传感器后端，默认 simulated",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--pin", default="D4", help="DHT22 数据引脚，例如 D4")
    parser.add_argument(
        "--i2c-address",
        type=_i2c_address,
        default=0x76,
        help="BME280 I2C 地址，0x76 或 0x77",
    )
    parser.add_argument("--samples", type=_positive_int, default=10)
    parser.add_argument("--interval", type=_non_negative_float, default=2.0)
    parser.add_argument("--retries", type=_non_negative_int, default=3)
    parser.add_argument("--retry-delay", type=_non_negative_float, default=1.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/environment.csv"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.simulate and args.sensor != "simulated":
        parser.error("--simulate 不能与真实传感器同时使用")

    sensor: Sensor | None = None
    try:
        sensor = make_sensor(
            args.sensor,
            pin=args.pin,
            i2c_address=args.i2c_address,
        )
        collect(
            sensor,
            samples=args.samples,
            interval=args.interval,
            output=args.output,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except (SensorDependencyError, SensorReadError, ValueError) as error:
        print(f"采集失败：{error}", file=sys.stderr)
        return 1
    finally:
        if sensor is not None:
            sensor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
