"""Explainable, offline energy scheduling for small edge devices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyWindow:
    """A future time window with local price and renewable availability."""

    name: str
    price_per_kwh: float
    solar_surplus_kw: float
    capacity_kw: float


@dataclass(frozen=True)
class FlexibleLoad:
    """An appliance that may be moved between time windows."""

    name: str
    power_kw: float
    duration_hours: float
    priority: int = 1

    @property
    def energy_kwh(self) -> float:
        return self.power_kw * self.duration_hours


@dataclass(frozen=True)
class ScheduleDecision:
    load: str
    window: str
    estimated_cost: float
    reason: str


class EnergyScheduler:
    """Greedy scheduler favouring solar, low prices and high-priority loads."""

    def schedule(
        self,
        loads: list[FlexibleLoad],
        windows: list[EnergyWindow],
    ) -> list[ScheduleDecision]:
        remaining = {window.name: window.capacity_kw for window in windows}
        decisions: list[ScheduleDecision] = []

        for load in sorted(loads, key=lambda item: (-item.priority, item.name)):
            eligible = [
                window
                for window in windows
                if remaining[window.name] >= load.power_kw
            ]
            if not eligible:
                decisions.append(
                    ScheduleDecision(
                        load.name,
                        "未安排",
                        0.0,
                        "所有时段容量不足，需要人工处理",
                    )
                )
                continue

            chosen = min(eligible, key=lambda window: self._score(load, window))
            remaining[chosen.name] -= load.power_kw
            solar_energy = min(
                load.energy_kwh,
                chosen.solar_surplus_kw * load.duration_hours,
            )
            grid_energy = load.energy_kwh - solar_energy
            cost = grid_energy * chosen.price_per_kwh
            reason = (
                f"优先级 {load.priority}；预计太阳能覆盖 "
                f"{solar_energy:.2f} kWh，电网购电 {grid_energy:.2f} kWh"
            )
            decisions.append(
                ScheduleDecision(load.name, chosen.name, round(cost, 4), reason)
            )

        return decisions

    @staticmethod
    def _score(load: FlexibleLoad, window: EnergyWindow) -> tuple[float, float]:
        solar_energy = min(
            load.energy_kwh,
            window.solar_surplus_kw * load.duration_hours,
        )
        grid_cost = (load.energy_kwh - solar_energy) * window.price_per_kwh
        return grid_cost, window.price_per_kwh
