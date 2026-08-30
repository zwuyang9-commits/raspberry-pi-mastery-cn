from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rpi_mastery.sensors import Sensor, SensorDependencyError, SensorReadError, make_sensor

CSV_HEADER = ["timestamp_utc", "temperature_c", "humidity_pct"]


@dataclass(frozen=True)
class QualityLimits:
    temperature_range: tuple[float, float] | None = None
    humidity_range: tuple[float, float] | None = None
    max_temperature_step: float | None = None
    max_humidity_step: float | None = None

    def __post_init__(self) -> None:
        for name, value_range in (
            ("temperature_range", self.temperature_range),
            ("humidity_range", self.humidity_range),
        ):
            if value_range is not None and (
                not all(math.isfinite(value) for value in value_range)
                or value_range[0] > value_range[1]
            ):
                raise ValueError(f"{name} must contain finite values in ascending order")
        for name, step in (
            ("max_temperature_step", self.max_temperature_step),
            ("max_humidity_step", self.max_humidity_step),
        ):
            if step is not None and (not math.isfinite(step) or step <= 0):
                raise ValueError(f"{name} must be positive")

    def validate(
        self,
        temperature: float,
        humidity: float,
        previous: tuple[float, float] | None,
    ) -> None:
        if self.temperature_range is not None and not (
            self.temperature_range[0] <= temperature <= self.temperature_range[1]
        ):
            raise SensorReadError(f"温度 {temperature:g}°C 超出质量范围")
        if self.humidity_range is not None and not (
            self.humidity_range[0] <= humidity <= self.humidity_range[1]
        ):
            raise SensorReadError(f"湿度 {humidity:g}% 超出质量范围")
        if previous is None:
            return
        if self.max_temperature_step is not None and (
            abs(temperature - previous[0]) > self.max_temperature_step
        ):
            raise SensorReadError("温度变化幅度超过质量限制")
        if self.max_humidity_step is not None and (
            abs(humidity - previous[1]) > self.max_humidity_step
        ):
            raise SensorReadError("湿度变化幅度超过质量限制")


@dataclass(frozen=True)
class CollectionSummary:
    samples: int
    temperature_min: float
    temperature_max: float
    temperature_average: float
    humidity_min: float
    humidity_max: float
    humidity_average: float


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
    quality: QualityLimits | None = None,
    previous: tuple[float, float] | None = None,
) -> tuple[float, float]:
    for attempt in range(retries + 1):
        try:
            reading = sensor.read()
            values = (reading.temperature_c, reading.humidity_pct)
            if quality is not None:
                quality.validate(*values, previous)
            return values
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
    quality: QualityLimits | None = None,
) -> CollectionSummary:
    """Append timestamped readings while preserving data from earlier runs."""

    _validate_collection_options(
        samples=samples,
        interval=interval,
        retries=retries,
        retry_delay=retry_delay,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_header = _needs_header(output)
    accepted: list[tuple[float, float]] = []

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
                quality=quality,
                previous=accepted[-1] if accepted else None,
            )
            accepted.append((temperature, humidity))
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
    temperatures = [item[0] for item in accepted]
    humidities = [item[1] for item in accepted]
    return CollectionSummary(
        samples=len(accepted),
        temperature_min=min(temperatures),
        temperature_max=max(temperatures),
        temperature_average=sum(temperatures) / len(temperatures),
        humidity_min=min(humidities),
        humidity_max=max(humidities),
        humidity_average=sum(humidities) / len(humidities),
    )


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


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("必须是有限数值")
    return parsed


def _positive_float(value: str) -> float:
    parsed = _finite_float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
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
    parser.add_argument(
        "--temperature-range",
        type=_finite_float,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="只接受指定温度范围内的读数",
    )
    parser.add_argument(
        "--humidity-range",
        type=_finite_float,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="只接受指定湿度范围内的读数",
    )
    parser.add_argument(
        "--max-temperature-step",
        type=_positive_float,
        help="相邻有效读数允许的最大温差",
    )
    parser.add_argument(
        "--max-humidity-step",
        type=_positive_float,
        help="相邻有效读数允许的最大湿度差",
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
        quality = QualityLimits(
            temperature_range=(tuple(args.temperature_range) if args.temperature_range else None),
            humidity_range=(tuple(args.humidity_range) if args.humidity_range else None),
            max_temperature_step=args.max_temperature_step,
            max_humidity_step=args.max_humidity_step,
        )
        summary = collect(
            sensor,
            samples=args.samples,
            interval=args.interval,
            output=args.output,
            retries=args.retries,
            retry_delay=args.retry_delay,
            quality=quality,
        )
        print(
            f"已保存 {summary.samples} 组；温度 {summary.temperature_min:.2f}–"
            f"{summary.temperature_max:.2f}°C（平均 {summary.temperature_average:.2f}°C），"
            f"湿度 {summary.humidity_min:.2f}–{summary.humidity_max:.2f}%"
            f"（平均 {summary.humidity_average:.2f}%）"
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
