"""Small, explainable rules engine for offline-first edge automation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str
    value: Any
    source: str
    timestamp: datetime

    @classmethod
    def now(cls, kind: str, value: Any, source: str) -> Event:
        return cls(kind, value, source, datetime.now(timezone.utc))


@dataclass(frozen=True)
class Action:
    target: str
    command: str
    value: Any
    reason: str


@dataclass(frozen=True)
class Rule:
    name: str
    event_kind: str
    predicate: Callable[[Event], bool]
    build_action: Callable[[Event], Action]


@dataclass(frozen=True)
class RuleFailure:
    rule: str
    phase: str
    error_type: str
    message: str


@dataclass(frozen=True)
class RuleEvaluation:
    actions: tuple[Action, ...]
    failures: tuple[RuleFailure, ...]


class RuleEngine:
    """Evaluates deterministic local rules and returns auditable actions."""

    def __init__(self, rules: list[Rule]) -> None:
        self._rules = list(rules)

    def evaluate(self, event: Event) -> list[Action]:
        actions: list[Action] = []
        for rule in self._rules:
            if rule.event_kind == event.kind and rule.predicate(event):
                actions.append(rule.build_action(event))
        return actions

    def evaluate_safely(self, event: Event) -> RuleEvaluation:
        """Isolate individual rule failures so other local rules can continue."""

        actions: list[Action] = []
        failures: list[RuleFailure] = []
        for rule in self._rules:
            if rule.event_kind != event.kind:
                continue
            try:
                matches = rule.predicate(event)
            except Exception as error:  # noqa: BLE001 - user rules may raise arbitrary errors
                failures.append(self._failure(rule, "predicate", error))
                continue
            if not matches:
                continue
            try:
                actions.append(rule.build_action(event))
            except Exception as error:  # noqa: BLE001 - user rules may raise arbitrary errors
                failures.append(self._failure(rule, "action", error))
        return RuleEvaluation(tuple(actions), tuple(failures))

    @staticmethod
    def _failure(rule: Rule, phase: str, error: Exception) -> RuleFailure:
        message = str(error).replace("\n", " ")[:200]
        return RuleFailure(
            rule=rule.name,
            phase=phase,
            error_type=type(error).__name__,
            message=message,
        )
