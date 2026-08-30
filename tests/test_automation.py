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


def test_safe_evaluation_isolates_predicate_and_action_failures():
    def broken_predicate(event):
        raise TypeError("sensor value is invalid")

    def broken_action(event):
        raise RuntimeError("relay unavailable")

    engine = RuleEngine(
        [
            Rule("bad-predicate", "temperature_c", broken_predicate, lambda event: None),
            Rule("bad-action", "temperature_c", lambda event: True, broken_action),
            Rule(
                "working",
                "temperature_c",
                lambda event: True,
                lambda event: Action("fan", "on", True, "fallback"),
            ),
        ]
    )

    result = engine.evaluate_safely(Event.now("temperature_c", 31, "lab"))

    assert result.actions == (Action("fan", "on", True, "fallback"),)
    assert [(failure.rule, failure.phase) for failure in result.failures] == [
        ("bad-predicate", "predicate"),
        ("bad-action", "action"),
    ]
    assert result.failures[0].error_type == "TypeError"
