"""Hardware adapters that keep application logic testable away from a Pi."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class DigitalOutput(Protocol):
    """Minimal contract implemented by LEDs, relays and simulated outputs."""

    @property
    def value(self) -> float: ...

    def set(self, value: float) -> None: ...

    def close(self) -> None: ...


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
