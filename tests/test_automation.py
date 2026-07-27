from rpi_mastery.automation import Action, Event, Rule, RuleEngine


def test_rule_engine_returns_explainable_action():
    engine = RuleEngine(
        [
            Rule(
                "hot",
                "temperature_c",
                lambda event: event.value >= 30,
                lambda event: Action("fan", "set", 1, "temperature threshold exceeded"),
            )
        ]
    )

    actions = engine.evaluate(Event.now("temperature_c", 31, "lab"))

    assert actions == [Action("fan", "set", 1, "temperature threshold exceeded")]


def test_rule_engine_ignores_unmatched_event():
    engine = RuleEngine(
        [Rule("leak", "water_leak", lambda event: event.value, lambda event: Action("valve", "close", 1, "leak"))]
    )
    assert engine.evaluate(Event.now("temperature_c", 21, "lab")) == []
