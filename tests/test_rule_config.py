import json

import pytest

from rpi_mastery.automation import Action, Event
from rpi_mastery.rule_config import ReloadableRuleEngine, RuleConfigError, load_rule_engine


def write_config(path, *, threshold=30):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "name": "hot",
                        "event_kind": "temperature_c",
                        "operator": "gte",
                        "value": threshold,
                        "action": {
                            "target": "fan",
                            "command": "set",
                            "value": 1,
                            "reason": "温度 {value}°C 达到阈值",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_loads_numeric_rule_and_formats_reason(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path)

    engine = load_rule_engine(path)

    assert engine.evaluate(Event.now("temperature_c", 29.9, "room")) == []
    assert engine.evaluate(Event.now("temperature_c", 31, "room")) == [
        Action("fan", "set", 1, "温度 31°C 达到阈值")
    ]


def test_numeric_rule_rejects_boolean_event_value(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path)

    assert load_rule_engine(path).evaluate(Event.now("temperature_c", True, "room")) == []


def test_numeric_rule_rejects_non_finite_event_value(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path)

    assert load_rule_engine(path).evaluate(Event.now("temperature_c", float("inf"), "room")) == []


def test_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path)
    content = path.read_text(encoding="utf-8").replace('"version": 1', '"version": 1, "version": 1')
    path.write_text(content, encoding="utf-8")

    with pytest.raises(RuleConfigError, match="duplicate JSON key: version"):
        load_rule_engine(path)


@pytest.mark.parametrize("threshold", [float("nan"), float("inf")])
def test_rejects_non_standard_numeric_thresholds(tmp_path, threshold):
    path = tmp_path / "rules.json"
    write_config(path, threshold=threshold)

    with pytest.raises(RuleConfigError, match="non-standard JSON number"):
        load_rule_engine(path)


def test_rejects_threshold_that_overflows_to_infinity(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path)
    content = path.read_text(encoding="utf-8").replace('"value": 30', '"value": 1e999', 1)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(RuleConfigError, match="threshold must be finite"):
        load_rule_engine(path)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda config: config.update(version=2), "unsupported"),
        (lambda config: config["rules"].append(config["rules"][0]), "duplicate"),
        (lambda config: config["rules"][0].update(operator="exec"), "unsupported operator"),
        (
            lambda config: config["rules"][0]["action"].update(reason="{value.__class__}"),
            "reason may only use",
        ),
    ],
)
def test_rejects_invalid_config(tmp_path, change, message):
    path = tmp_path / "rules.json"
    write_config(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    change(config)
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(RuleConfigError, match=message):
        load_rule_engine(path)


def test_failed_reload_keeps_last_valid_rules(tmp_path):
    path = tmp_path / "rules.json"
    write_config(path, threshold=30)
    engine = ReloadableRuleEngine(path)
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(RuleConfigError):
        engine.reload()

    assert engine.evaluate(Event.now("temperature_c", 31, "room"))[0].target == "fan"
