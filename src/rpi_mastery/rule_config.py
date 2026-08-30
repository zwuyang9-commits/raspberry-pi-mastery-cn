"""Validated JSON configuration for the local automation rule engine."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from string import Formatter
from typing import Any

from .automation import Action, Event, Rule, RuleEngine


class RuleConfigError(ValueError):
    """Raised when a rule file is malformed or unsafe to activate."""


_COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    "gt": lambda actual, expected: actual > expected,
    "gte": lambda actual, expected: actual >= expected,
    "lt": lambda actual, expected: actual < expected,
    "lte": lambda actual, expected: actual <= expected,
}


def _required_text(raw: dict[str, Any], key: str, rule_name: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuleConfigError(f"rule {rule_name}: {key} must be non-empty text")
    return value.strip()


def _numeric_predicate(operator: str, expected: Any, rule_name: str) -> Callable[[Event], bool]:
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        raise RuleConfigError(f"rule {rule_name}: numeric operator requires a number")
    threshold = float(expected)
    comparison = _COMPARISONS[operator]

    def matches(event: Event) -> bool:
        if isinstance(event.value, bool) or not isinstance(event.value, (int, float)):
            return False
        return comparison(float(event.value), threshold)

    return matches


def _build_predicate(operator: str, expected: Any, rule_name: str) -> Callable[[Event], bool]:
    if operator in _COMPARISONS:
        return _numeric_predicate(operator, expected, rule_name)
    if operator == "eq":
        return lambda event: type(event.value) is type(expected) and event.value == expected
    if operator == "is_true":
        if expected is not True:
            raise RuleConfigError(f"rule {rule_name}: is_true value must be true")
        return lambda event: event.value is True
    if operator == "is_false":
        if expected is not False:
            raise RuleConfigError(f"rule {rule_name}: is_false value must be false")
        return lambda event: event.value is False
    raise RuleConfigError(f"rule {rule_name}: unsupported operator {operator!r}")


def load_rule_engine(path: str | Path) -> RuleEngine:
    """Parse and validate an entire rule file before returning an engine."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuleConfigError(f"cannot read rule config: {config_path}") from error
    if not isinstance(raw, dict) or set(raw) != {"version", "rules"}:
        raise RuleConfigError("config must contain only version and rules")
    if raw["version"] != 1:
        raise RuleConfigError(f"unsupported rule config version: {raw['version']!r}")
    if not isinstance(raw["rules"], list) or not raw["rules"]:
        raise RuleConfigError("rules must be a non-empty list")

    rules: list[Rule] = []
    names: set[str] = set()
    for index, item in enumerate(raw["rules"], start=1):
        if not isinstance(item, dict):
            raise RuleConfigError(f"rule {index}: must be an object")
        allowed = {"name", "event_kind", "operator", "value", "action"}
        if set(item) != allowed:
            raise RuleConfigError(f"rule {index}: fields must be {sorted(allowed)}")
        name = _required_text(item, "name", str(index))
        if name in names:
            raise RuleConfigError(f"duplicate rule name: {name}")
        names.add(name)
        event_kind = _required_text(item, "event_kind", name)
        operator = _required_text(item, "operator", name)
        predicate = _build_predicate(operator, item["value"], name)

        action = item["action"]
        if not isinstance(action, dict) or set(action) != {"target", "command", "value", "reason"}:
            raise RuleConfigError(f"rule {name}: invalid action fields")
        target = _required_text(action, "target", name)
        command = _required_text(action, "command", name)
        reason = _required_text(action, "reason", name)
        try:
            placeholders = list(Formatter().parse(reason))
        except ValueError as error:
            raise RuleConfigError(f"rule {name}: invalid reason template") from error
        for _, field, format_spec, conversion in placeholders:
            if field is not None and (
                field not in {"value", "source"} or format_spec or conversion is not None
            ):
                raise RuleConfigError(
                    f"rule {name}: reason may only use {{value}} and {{source}}"
                )
        action_value = action["value"]

        def build_action(
            event: Event,
            *,
            target: str = target,
            command: str = command,
            value: Any = action_value,
            reason: str = reason,
        ) -> Action:
            return Action(target, command, value, reason.format(value=event.value, source=event.source))

        rules.append(Rule(name, event_kind, predicate, build_action))
    return RuleEngine(rules)


class ReloadableRuleEngine:
    """Keeps the last valid engine when a replacement config is rejected."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._engine = load_rule_engine(self.path)

    def reload(self) -> None:
        replacement = load_rule_engine(self.path)
        self._engine = replacement

    def evaluate(self, event: Event) -> list[Action]:
        return self._engine.evaluate(event)
