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
