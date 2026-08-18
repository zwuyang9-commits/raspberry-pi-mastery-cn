"""Explainable, offline energy scheduling for small edge devices."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def _require_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 不能为空")


def _require_number(
    value: float,
    field: str,
    *,
    allow_zero: bool = False,
) -> None:
    try:
        valid = (
            not isinstance(value, bool)
            and isfinite(value)
            and (value >= 0 if allow_zero else value > 0)
        )
    except TypeError:
        valid = False
    if not valid:
        qualifier = "非负数" if allow_zero else "正数"
        raise ValueError(f"{field} 必须是有限{qualifier}")


@dataclass(frozen=True)
class EnergyWindow:
    """A future time window with local price and renewable availability.

    Four-argument callers retain a full-day planning window by default.
    """

    name: str
    price_per_kwh: float
    solar_surplus_kw: float
    capacity_kw: float
    duration_hours: float = 24.0

    def __post_init__(self) -> None:
        _require_name(self.name, "时段名称")
        _require_number(self.price_per_kwh, "电价", allow_zero=True)
        _require_number(self.solar_surplus_kw, "太阳能余量", allow_zero=True)
        _require_number(self.capacity_kw, "时段容量")
        _require_number(self.duration_hours, "时段时长")

    @property
    def solar_budget_kwh(self) -> float:
        """Total solar energy available across the complete window."""

        return self.solar_surplus_kw * self.duration_hours


@dataclass(frozen=True)
class FlexibleLoad:
    """An appliance that may be moved between time windows."""

    name: str
    power_kw: float
    duration_hours: float
    priority: int = 1

    def __post_init__(self) -> None:
        _require_name(self.name, "负载名称")
        _require_number(self.power_kw, "负载功率")
        _require_number(self.duration_hours, "运行时长")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("优先级必须是正整数")
        if self.priority <= 0:
            raise ValueError("优先级必须是正整数")

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
        self._require_unique_names(loads, "负载")
        self._require_unique_names(windows, "时段")

        remaining_capacity = {window.name: window.capacity_kw for window in windows}
        remaining_solar_power = {
            window.name: window.solar_surplus_kw for window in windows
        }
        remaining_solar = {
            window.name: window.solar_budget_kwh for window in windows
        }
        decisions: list[ScheduleDecision] = []

        for load in sorted(loads, key=lambda item: (-item.priority, item.name)):
            eligible = [
                window
                for window in windows
                if load.duration_hours <= window.duration_hours
                and load.power_kw <= remaining_capacity[window.name]
            ]
            if not eligible:
                decisions.append(
                    ScheduleDecision(
                        load.name,
                        "未安排",
                        0.0,
                        "没有时段能容纳完整运行时长，或剩余容量不足，"
                        "需要人工处理",
                    )
                )
                continue

            chosen = min(
                eligible,
                key=lambda window: self._score(
                    load,
                    window,
                    remaining_solar_power[window.name],
                    remaining_solar[window.name],
                ),
            )
            remaining_capacity[chosen.name] -= load.power_kw
            solar_energy = min(
                load.energy_kwh,
                remaining_solar[chosen.name],
                remaining_solar_power[chosen.name] * load.duration_hours,
            )
            solar_power = solar_energy / load.duration_hours
            remaining_solar_power[chosen.name] = max(
                0.0,
                remaining_solar_power[chosen.name] - solar_power,
            )
            remaining_solar[chosen.name] = max(
                0.0,
                remaining_solar[chosen.name] - solar_energy,
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
    def _score(
        load: FlexibleLoad,
        window: EnergyWindow,
        remaining_solar_kw: float | None = None,
        remaining_solar_kwh: float | None = None,
    ) -> tuple[float, float]:
        solar_power = (
            window.solar_surplus_kw
            if remaining_solar_kw is None
            else remaining_solar_kw
        )
        solar_budget = (
            window.solar_budget_kwh
            if remaining_solar_kwh is None
            else remaining_solar_kwh
        )
        solar_energy = min(
            load.energy_kwh,
            solar_budget,
            solar_power * load.duration_hours,
        )
        grid_cost = (load.energy_kwh - solar_energy) * window.price_per_kwh
        return grid_cost, window.price_per_kwh

    @staticmethod
    def _require_unique_names(items: list[object], kind: str) -> None:
        names = [item.name.strip() for item in items]
        if len(names) != len(set(names)):
            raise ValueError(f"{kind}名称必须唯一")
