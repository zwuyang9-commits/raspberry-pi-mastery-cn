import importlib

import pytest

from rpi_mastery.automation import Event

home_hub = importlib.import_module("projects.05_resilient_home_hub.main")


def test_false_string_cannot_be_mistaken_for_a_water_leak():
    engine = home_hub.build_engine()
    event = Event.now("water_leak", "false", "utility-room")

    with pytest.raises(TypeError, match="布尔值"):
        engine.evaluate(event)


def test_boolean_false_does_not_close_water_valve():
    engine = home_hub.build_engine()

    actions = engine.evaluate(Event.now("water_leak", False, "utility-room"))

    assert actions == []
