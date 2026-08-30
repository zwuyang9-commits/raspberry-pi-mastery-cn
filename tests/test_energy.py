import pytest

from rpi_mastery.energy import EnergyScheduler, EnergyWindow, FlexibleLoad


def test_scheduler_prefers_free_solar_energy():
    windows = [
        EnergyWindow("solar", 0.8, solar_surplus_kw=1.0, capacity_kw=2.0),
        EnergyWindow("night", 0.2, solar_surplus_kw=0.0, capacity_kw=2.0),
    ]
    load = FlexibleLoad("washer", power_kw=1.0, duration_hours=1.0)

    decision = EnergyScheduler().schedule([load], windows)[0]

    assert decision.window == "solar"
    assert decision.estimated_cost == 0.0


def test_scheduler_reports_capacity_shortage():
    windows = [EnergyWindow("small", 0.2, solar_surplus_kw=0.0, capacity_kw=0.5)]
    load = FlexibleLoad("heater", power_kw=2.0, duration_hours=1.0)

    decision = EnergyScheduler().schedule([load], windows)[0]

    assert decision.window == "未安排"
    assert "增加 1.50 kW 容量" in decision.reason
    assert decision.closest_window == "small"
    assert decision.capacity_shortfall_kw == 1.5
    assert decision.duration_shortfall_hours == 0.0


def test_scheduler_does_not_reuse_one_window_solar_budget():
    windows = [
        EnergyWindow(
            "one-hour solar",
            1.0,
            solar_surplus_kw=1.0,
            capacity_kw=2.0,
            duration_hours=1.0,
        )
    ]
    loads = [
        FlexibleLoad("first", power_kw=1.0, duration_hours=1.0),
        FlexibleLoad("second", power_kw=1.0, duration_hours=1.0),
    ]

    decisions = EnergyScheduler().schedule(loads, windows)

    assert [decision.estimated_cost for decision in decisions] == [0.0, 1.0]
    assert "太阳能覆盖 0.00 kWh" in decisions[1].reason


def test_scheduler_rejects_load_longer_than_window():
    windows = [
        EnergyWindow(
            "short",
            0.2,
            solar_surplus_kw=0.0,
            capacity_kw=2.0,
            duration_hours=1.0,
        )
    ]
    load = FlexibleLoad("long cycle", power_kw=1.0, duration_hours=1.5)

    decision = EnergyScheduler().schedule([load], windows)[0]

    assert decision.window == "未安排"
    assert "延长 0.50 小时" in decision.reason
    assert decision.closest_window == "short"
    assert decision.duration_shortfall_hours == 0.5


def test_scheduler_tracks_shared_window_power_capacity():
    windows = [
        EnergyWindow(
            "limited",
            0.2,
            solar_surplus_kw=0.0,
            capacity_kw=1.0,
            duration_hours=1.0,
        )
    ]
    loads = [
        FlexibleLoad("first", power_kw=1.0, duration_hours=1.0),
        FlexibleLoad("second", power_kw=1.0, duration_hours=1.0),
    ]

    decisions = EnergyScheduler().schedule(loads, windows)

    assert decisions[0].window == "limited"
    assert decisions[1].window == "未安排"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price_per_kwh", -0.01),
        ("solar_surplus_kw", -0.01),
        ("capacity_kw", 0.0),
        ("duration_hours", 0.0),
    ],
)
def test_energy_window_rejects_invalid_numbers(field, value):
    values = {
        "name": "invalid",
        "price_per_kwh": 0.2,
        "solar_surplus_kw": 0.0,
        "capacity_kw": 1.0,
        "duration_hours": 1.0,
    }
    values[field] = value

    with pytest.raises(ValueError):
        EnergyWindow(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("power_kw", 0.0),
        ("duration_hours", 0.0),
        ("priority", 0),
    ],
)
def test_flexible_load_rejects_non_positive_numbers(field, value):
    values = {
        "name": "invalid",
        "power_kw": 1.0,
        "duration_hours": 1.0,
        "priority": 1,
    }
    values[field] = value

    with pytest.raises(ValueError):
        FlexibleLoad(**values)


def test_scheduler_requires_unique_window_and_load_names():
    duplicate_windows = [
        EnergyWindow("same", 0.2, 0.0, 1.0),
        EnergyWindow("same", 0.3, 0.0, 1.0),
    ]
    duplicate_loads = [
        FlexibleLoad("same", 0.2, 1.0),
        FlexibleLoad("same", 0.3, 1.0),
    ]

    with pytest.raises(ValueError, match="时段名称必须唯一"):
        EnergyScheduler().schedule([], duplicate_windows)
    with pytest.raises(ValueError, match="负载名称必须唯一"):
        EnergyScheduler().schedule(duplicate_loads, [])


def test_scheduler_explains_when_no_windows_exist():
    decision = EnergyScheduler().schedule(
        [FlexibleLoad("heater", power_kw=2.0, duration_hours=1.0)],
        [],
    )[0]

    assert decision.window == "未安排"
    assert decision.closest_window is None
    assert "新增时段" in decision.reason


def test_scheduler_chooses_closest_window_by_relative_shortfall():
    load = FlexibleLoad("heater", power_kw=2.0, duration_hours=2.0)
    windows = [
        EnergyWindow("power-short", 0.3, 0.0, capacity_kw=1.5, duration_hours=2.0),
        EnergyWindow("time-short", 0.2, 0.0, capacity_kw=2.0, duration_hours=1.0),
    ]

    decision = EnergyScheduler().schedule([load], windows)[0]

    assert decision.closest_window == "power-short"
    assert decision.capacity_shortfall_kw == 0.5
