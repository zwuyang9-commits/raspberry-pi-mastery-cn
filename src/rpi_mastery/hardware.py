"""Hardware adapters that keep application logic testable away from a Pi."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock, Timer
from typing import Any, Protocol


class DigitalOutput(Protocol):
    """Minimal contract implemented by LEDs, relays and simulated outputs."""

    @property
    def value(self) -> float: ...

    def set(self, value: float) -> None: ...

    def close(self) -> None: ...


class WatchdogOutput:
    """Returns an output to a safe value when commands stop arriving."""

    def __init__(
        self,
        output: DigitalOutput,
        *,
        timeout: float,
        safe_value: float = 0.0,
        timer_factory: Callable[[float, Callable[[], None]], Any] = Timer,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("watchdog timeout must be positive")
        if not math.isfinite(safe_value) or not 0.0 <= safe_value <= 1.0:
            raise ValueError("safe value must be between 0 and 1")
        self._output = output
        self.timeout = timeout
        self.safe_value = safe_value
        self._timer_factory = timer_factory
        self._timer: Any | None = None
        self._generation = 0
        self._closed = False
        self._triggered = False
        self._watchdog_error: Exception | None = None
        self._lock = RLock()

    @property
    def value(self) -> float:
        return self._output.value

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def watchdog_error(self) -> Exception | None:
        return self._watchdog_error

    def set(self, value: float) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("output is closed")
            self._output.set(value)
            self._triggered = False
            self._watchdog_error = None
            self._arm()

    def pet(self) -> None:
        """Refresh the timeout without changing the current output value."""

        with self._lock:
            if self._closed:
                raise RuntimeError("output is closed")
            self._arm()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            if self._timer is not None:
                self._timer.cancel()
            self._output.close()

    def _arm(self) -> None:
        self._generation += 1
        generation = self._generation
        if self._timer is not None:
            self._timer.cancel()
        timer = self._timer_factory(
            self.timeout,
            lambda: self._expire(generation),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        self._timer = timer
        timer.start()

    def _expire(self, generation: int) -> None:
        with self._lock:
            if self._closed or generation != self._generation:
                return
            try:
                self._output.set(self.safe_value)
                self._triggered = True
            except Exception as error:  # noqa: BLE001 - adapters may expose driver-specific errors
                self._watchdog_error = error


@dataclass
class SimulatedDigitalOutput:
    """In-memory output used for learning, CI and dry runs."""

    _value: float = 0.0
    history: list[float] = field(default_factory=list)
    closed: bool = False

    @property
    def value(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        if self.closed:
            raise RuntimeError("output is closed")
        if not 0.0 <= value <= 1.0:
            raise ValueError("output value must be between 0 and 1")
        self._value = float(value)
        self.history.append(self._value)

    def close(self) -> None:
        self._value = 0.0
        self.closed = True


class GPIOZeroPWMOutput:
    """gpiozero-backed PWM output; import is delayed for non-Pi computers."""

    def __init__(self, pin: int) -> None:
        from gpiozero import PWMLED

        self._device = PWMLED(pin)

    @property
    def value(self) -> float:
        return float(self._device.value)

    def set(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("output value must be between 0 and 1")
        self._device.value = value

    def close(self) -> None:
        self._device.off()
        self._device.close()


def make_output(pin: int, simulate: bool) -> DigitalOutput:
    return SimulatedDigitalOutput() if simulate else GPIOZeroPWMOutput(pin)
