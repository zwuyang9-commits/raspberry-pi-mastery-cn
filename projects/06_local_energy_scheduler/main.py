from __future__ import annotations

import json

from rpi_mastery.energy import EnergyScheduler, EnergyWindow, FlexibleLoad


def demo() -> None:
    windows = [
        EnergyWindow(
            "中午光伏",
            0.55,
            solar_surplus_kw=2.0,
            capacity_kw=3.0,
            duration_hours=4.0,
        ),
        EnergyWindow(
            "晚间高峰",
            1.20,
            solar_surplus_kw=0.0,
            capacity_kw=2.0,
            duration_hours=4.0,
        ),
        EnergyWindow(
            "夜间低谷",
            0.35,
            solar_surplus_kw=0.0,
            capacity_kw=3.0,
            duration_hours=8.0,
        ),
    ]
    loads = [
        FlexibleLoad("热水器", power_kw=2.0, duration_hours=1.0, priority=3),
        FlexibleLoad("洗衣机", power_kw=0.8, duration_hours=1.5, priority=2),
        FlexibleLoad("电动自行车", power_kw=0.5, duration_hours=3.0, priority=1),
    ]

    decisions = EnergyScheduler().schedule(loads, windows)
    for decision in decisions:
        print(json.dumps(decision.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    demo()
