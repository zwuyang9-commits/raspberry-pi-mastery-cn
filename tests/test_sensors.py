import csv
import importlib
import math
import sys
from types import ModuleType

import pytest

from rpi_mastery.sensors import (
    BME280Sensor,
    DHT22Sensor,
    Reading,
    SensorReadError,
    SimulatedSensor,
    make_sensor,
)

station = importlib.import_module("projects.02_environment_station.main")


def test_simulated_sensor_is_deterministic_and_changes_over_time():
    first = SimulatedSensor()
    second = SimulatedSensor()

    first_readings = [first.read() for _ in range(3)]
    second_readings = [second.read() for _ in range(3)]

    assert first_readings == second_readings
    assert len(set(first_readings)) == 3


@pytest.mark.parametrize(
    ("temperature", "humidity"),
    [
        (math.nan, 50.0),
        (20.0, math.inf),
        (20.0, -0.1),
        (20.0, 100.1),
    ],
)
def test_reading_rejects_invalid_values(temperature, humidity):
    with pytest.raises(ValueError):
        Reading(temperature, humidity)


def test_dht22_adapter_loads_driver_only_when_created(monkeypatch):
    board_pin = object()
    fake_board = ModuleType("board")
    fake_board.D4 = board_pin

    created = []

    class FakeDevice:
        temperature = 23.25
        humidity = 56.5

        def __init__(self, pin, *, use_pulseio):
            created.append((pin, use_pulseio))
            self.closed = False

        def exit(self):
            self.closed = True

    fake_driver = ModuleType("adafruit_dht")
    fake_driver.DHT22 = FakeDevice
    monkeypatch.setitem(sys.modules, "board", fake_board)
    monkeypatch.setitem(sys.modules, "adafruit_dht", fake_driver)

    sensor = DHT22Sensor("d4")

    assert sensor.read() == Reading(23.25, 56.5)
    assert created == [(board_pin, False)]
    sensor.close()
    assert sensor._device.closed


def test_bme280_adapter_supports_both_common_addresses(monkeypatch):
    class FakeI2C:
        def __init__(self):
            self.closed = False

        def deinit(self):
            self.closed = True

    bus = FakeI2C()
    fake_board = ModuleType("board")
    fake_board.I2C = lambda: bus

    class FakeDevice:
        temperature = 19.75
        relative_humidity = 48.25

        def __init__(self, i2c, *, address):
            assert i2c is bus
            self.address = address

    fake_basic = ModuleType("adafruit_bme280.basic")
    fake_basic.Adafruit_BME280_I2C = FakeDevice
    fake_package = ModuleType("adafruit_bme280")
    fake_package.basic = fake_basic
    monkeypatch.setitem(sys.modules, "board", fake_board)
    monkeypatch.setitem(sys.modules, "adafruit_bme280", fake_package)
    monkeypatch.setitem(sys.modules, "adafruit_bme280.basic", fake_basic)

    sensor = BME280Sensor(0x77)

    assert sensor.read() == Reading(19.75, 48.25)
    assert sensor._device.address == 0x77
    sensor.close()
    assert bus.closed


def test_bme280_releases_i2c_when_device_initialization_fails(monkeypatch):
    class FakeI2C:
        def __init__(self):
            self.closed = False

        def deinit(self):
            self.closed = True

    bus = FakeI2C()
    fake_board = ModuleType("board")
    fake_board.I2C = lambda: bus

    class BrokenDevice:
        def __init__(self, i2c, *, address):
            assert i2c is bus
            assert address == 0x76
            raise RuntimeError("sensor did not acknowledge")

    fake_basic = ModuleType("adafruit_bme280.basic")
    fake_basic.Adafruit_BME280_I2C = BrokenDevice
    fake_package = ModuleType("adafruit_bme280")
    fake_package.basic = fake_basic
    monkeypatch.setitem(sys.modules, "board", fake_board)
    monkeypatch.setitem(sys.modules, "adafruit_bme280", fake_package)
    monkeypatch.setitem(sys.modules, "adafruit_bme280.basic", fake_basic)

    with pytest.raises(RuntimeError, match="did not acknowledge"):
        BME280Sensor()

    assert bus.closed


def test_make_sensor_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown sensor kind"):
        make_sensor("usb-weather-station")


def test_collect_appends_rows_without_repeating_header(tmp_path):
    output = tmp_path / "environment.csv"

    summary = station.collect(
        SimulatedSensor(),
        samples=2,
        interval=0,
        output=output,
        sleep=lambda _: None,
    )
    station.collect(
        SimulatedSensor(),
        samples=1,
        interval=0,
        output=output,
        sleep=lambda _: None,
    )

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == station.CSV_HEADER
    assert len(rows) == 4
    assert sum(row == station.CSV_HEADER for row in rows) == 1
    assert summary.samples == 2
    assert summary.temperature_min <= summary.temperature_average <= summary.temperature_max


def test_collect_retries_transient_failures(tmp_path, capsys):
    class FlakySensor:
        def __init__(self):
            self.calls = 0

        def read(self):
            self.calls += 1
            if self.calls < 3:
                raise SensorReadError("not ready")
            return Reading(21.5, 47.0)

        def close(self):
            return None

    sensor = FlakySensor()
    sleeps = []

    station.collect(
        sensor,
        samples=1,
        interval=0,
        output=tmp_path / "environment.csv",
        retries=2,
        retry_delay=0.25,
        sleep=sleeps.append,
    )

    assert sensor.calls == 3
    assert sleeps == [0.25, 0.25]
    assert "读取失败" in capsys.readouterr().err


def test_collect_validates_before_creating_output(tmp_path):
    output = tmp_path / "environment.csv"

    with pytest.raises(ValueError, match="samples"):
        station.collect(
            SimulatedSensor(),
            samples=0,
            interval=0,
            output=output,
        )

    assert not output.exists()


def test_quality_limits_retry_spike_and_keep_only_accepted_readings(tmp_path):
    class ScriptedSensor:
        def __init__(self):
            self.readings = iter(
                [
                    Reading(20.0, 50.0),
                    Reading(40.0, 51.0),
                    Reading(21.0, 51.0),
                ]
            )

        def read(self):
            return next(self.readings)

        def close(self):
            return None

    sleeps = []
    output = tmp_path / "environment.csv"
    summary = station.collect(
        ScriptedSensor(),
        samples=2,
        interval=0,
        output=output,
        retries=1,
        retry_delay=0.25,
        sleep=sleeps.append,
        quality=station.QualityLimits(max_temperature_step=5.0),
    )

    assert sleeps == [0, 0.25]
    assert summary.temperature_max == 21.0
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["temperature_c"] for row in rows] == ["20.00", "21.00"]


def test_quality_limits_reject_reversed_range():
    with pytest.raises(ValueError, match="ascending"):
        station.QualityLimits(temperature_range=(30.0, 10.0))
