from typing import ClassVar

import pytest

from rpi_mastery.hardware import SimulatedDigitalOutput, WatchdogOutput


def test_simulated_output_tracks_values_and_closes_safely():
    output = SimulatedDigitalOutput()
    output.set(0.25)
    output.set(1.0)
    output.close()

    assert output.history == [0.25, 1.0]
    assert output.value == 0.0
    assert output.closed


def test_simulated_output_rejects_unsafe_range():
    output = SimulatedDigitalOutput()
    with pytest.raises(ValueError):
        output.set(1.1)


class FakeTimer:
    created: ClassVar[list["FakeTimer"]] = []

    def __init__(self, timeout, callback):
        self.timeout = timeout
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.daemon = False
        self.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback()


def test_watchdog_returns_output_to_safe_value():
    FakeTimer.created = []
    underlying = SimulatedDigitalOutput()
    output = WatchdogOutput(underlying, timeout=5, timer_factory=FakeTimer)

    output.set(0.75)
    timer = FakeTimer.created[-1]
    timer.fire()

    assert timer.started
    assert timer.daemon
    assert output.value == 0.0
    assert output.triggered is True
    assert underlying.history == [0.75, 0.0]


def test_watchdog_ignores_replaced_timer_and_close_is_idempotent():
    FakeTimer.created = []
    underlying = SimulatedDigitalOutput()
    output = WatchdogOutput(underlying, timeout=5, timer_factory=FakeTimer)
    output.set(0.25)
    old_timer = FakeTimer.created[-1]
    output.set(0.5)

    old_timer.fire()
    assert output.value == 0.5
    assert old_timer.cancelled

    output.close()
    output.close()
    FakeTimer.created[-1].fire()
    assert output.value == 0.0
    assert underlying.closed


def test_watchdog_pet_refreshes_timeout_without_changing_value():
    FakeTimer.created = []
    output = WatchdogOutput(
        SimulatedDigitalOutput(),
        timeout=5,
        timer_factory=FakeTimer,
    )
    output.set(0.4)
    first = FakeTimer.created[-1]

    output.pet()

    assert first.cancelled
    assert len(FakeTimer.created) == 2
    assert output.value == 0.4


def test_watchdog_validates_timeout_and_safe_value():
    with pytest.raises(ValueError, match="timeout"):
        WatchdogOutput(SimulatedDigitalOutput(), timeout=0)
    with pytest.raises(ValueError, match="safe value"):
        WatchdogOutput(SimulatedDigitalOutput(), timeout=1, safe_value=1.1)
