"""Temperature and humidity sensors with optional Raspberry Pi adapters."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Protocol


class Sensor(Protocol):
    """Small interface shared by simulated and physical sensors."""

    def read(self) -> Reading: ...

    def close(self) -> None: ...


class SensorDependencyError(RuntimeError):
    """Raised when an optional hardware driver is not installed."""


class SensorReadError(RuntimeError):
    """Raised when a physical sensor cannot return a valid reading."""


@dataclass(frozen=True)
class Reading:
    temperature_c: float
    humidity_pct: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.temperature_c):
            raise ValueError("temperature must be finite")
        if not -100.0 <= self.temperature_c <= 150.0:
            raise ValueError("temperature is outside the supported range")
        if not math.isfinite(self.humidity_pct):
            raise ValueError("humidity must be finite")
        if not 0.0 <= self.humidity_pct <= 100.0:
            raise ValueError("humidity must be between 0 and 100")


class SimulatedSensor:
    """Deterministic signal useful for tutorials, tests and dry runs."""

    def __init__(self) -> None:
        self._index = 0

    def read(self) -> Reading:
        reading = Reading(
            temperature_c=22.0 + math.sin(self._index / 5),
            humidity_pct=50.0 + 4.0 * math.cos(self._index / 7),
        )
        self._index += 1
        return reading

    def close(self) -> None:
        return None


class DHT22Sensor:
    """DHT22 adapter using Adafruit CircuitPython, imported only on demand."""

    def __init__(self, pin: str = "D4") -> None:
        try:
            import adafruit_dht
            import board
        except ImportError as error:
            raise SensorDependencyError(
                "DHT22 需要 Raspberry Pi 上的 board 和 adafruit-circuitpython-dht"
            ) from error

        normalized_pin = pin.strip().upper()
        if re.fullmatch(r"D\d+", normalized_pin) is None:
            raise ValueError("DHT22 pin must look like D4 or D18")
        board_pin = getattr(board, normalized_pin, None)
        if board_pin is None:
            raise ValueError(f"board does not provide pin {normalized_pin}")

        self._device: Any = adafruit_dht.DHT22(board_pin, use_pulseio=False)

    def read(self) -> Reading:
        try:
            temperature = float(self._device.temperature)
            humidity = float(self._device.humidity)
            return Reading(temperature, humidity)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise SensorReadError(f"DHT22 读取失败: {error}") from error

    def close(self) -> None:
        self._device.exit()


class BME280Sensor:
    """BME280 I2C adapter using Adafruit CircuitPython."""

    def __init__(self, address: int = 0x76) -> None:
        if address not in (0x76, 0x77):
            raise ValueError("BME280 address must be 0x76 or 0x77")

        try:
            import board
            from adafruit_bme280 import basic as adafruit_bme280
        except ImportError as error:
            raise SensorDependencyError(
                "BME280 需要 Raspberry Pi 上的 board 和 adafruit-circuitpython-bme280"
            ) from error

        self._i2c: Any = board.I2C()
        self._device: Any = adafruit_bme280.Adafruit_BME280_I2C(
            self._i2c,
            address=address,
        )

    def read(self) -> Reading:
        try:
            return Reading(
                temperature_c=float(self._device.temperature),
                humidity_pct=float(self._device.relative_humidity),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise SensorReadError(f"BME280 读取失败: {error}") from error

    def close(self) -> None:
        deinit = getattr(self._i2c, "deinit", None)
        if deinit is not None:
            deinit()


def make_sensor(
    kind: str,
    *,
    pin: str = "D4",
    i2c_address: int = 0x76,
) -> Sensor:
    """Build a sensor without importing optional drivers for other backends."""

    normalized_kind = kind.strip().lower()
    if normalized_kind == "simulated":
        return SimulatedSensor()
    if normalized_kind == "dht22":
        return DHT22Sensor(pin)
    if normalized_kind == "bme280":
        return BME280Sensor(i2c_address)
    raise ValueError(f"unknown sensor kind: {kind}")
