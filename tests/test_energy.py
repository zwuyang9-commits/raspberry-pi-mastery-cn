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
    assert "容量不足" in decision.reason
