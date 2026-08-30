"""Durable at-least-once queue for local automation actions."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .audit import AuditLog
from .automation import Action


class ActionQueueError(ValueError):
    """Raised when durable queue state or an operation is invalid."""


@dataclass(frozen=True)
class QueuedAction:
    action_id: str
    action: Action
    enqueued_at: datetime
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class DispatchReport:
    processed: int
    completed: tuple[str, ...]
    failed: tuple[str, ...]


class DurableActionQueue:
    """Reconstructs pending work from an append-only audit log after restarts."""

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit
        self._lock = RLock()

    def enqueue(
        self,
        action: Action,
        *,
        action_id: str | None = None,
        now: datetime | None = None,
    ) -> QueuedAction:
        identifier = action_id or uuid4().hex
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", identifier) is None:
            raise ActionQueueError("action_id has an invalid format")
        try:
            json.dumps(action.value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ActionQueueError("action value must be JSON serializable") from error

        with self._lock:
            if identifier in self._known_ids():
                raise ActionQueueError(f"action_id already exists: {identifier}")
            timestamp = now or datetime.now(timezone.utc)
            entry = self.audit.append(
                "queued_action_created",
                action.target,
                {
                    "action_id": identifier,
                    "command": action.command,
                    "value": action.value,
                    "reason": action.reason,
                },
                timestamp=timestamp,
            )
            return QueuedAction(identifier, action, entry.timestamp)

    def pending(self) -> tuple[QueuedAction, ...]:
        with self._lock:
            active: dict[str, QueuedAction] = {}
            order: list[str] = []
            for entry in self.audit.read():
                if not entry.kind.startswith("queued_action_"):
                    continue
                identifier = entry.payload.get("action_id")
                if not isinstance(identifier, str):
                    raise ActionQueueError("queue record is missing action_id")
                if entry.kind == "queued_action_created":
                    if identifier in active or identifier in order:
                        raise ActionQueueError(f"duplicate queued action: {identifier}")
                    try:
                        action = Action(
                            target=entry.source,
                            command=str(entry.payload["command"]),
                            value=entry.payload["value"],
                            reason=str(entry.payload["reason"]),
                        )
                    except KeyError as error:
                        raise ActionQueueError(f"invalid queued action: {identifier}") from error
                    active[identifier] = QueuedAction(identifier, action, entry.timestamp)
                    order.append(identifier)
                elif entry.kind == "queued_action_attempted" and identifier in active:
                    item = active[identifier]
                    active[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts + 1,
                        last_error=item.last_error,
                    )
                elif entry.kind == "queued_action_failed" and identifier in active:
                    item = active[identifier]
                    active[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts,
                        last_error=str(entry.payload.get("error", "unknown error")),
                    )
                elif entry.kind == "queued_action_completed":
                    active.pop(identifier, None)
            return tuple(active[identifier] for identifier in order if identifier in active)

    def dispatch(
        self,
        handler: Callable[[QueuedAction], None],
        *,
        max_items: int | None = None,
        now: datetime | None = None,
    ) -> DispatchReport:
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be positive")
        timestamp = now or datetime.now(timezone.utc)
        completed: list[str] = []
        failed: list[str] = []
        with self._lock:
            items = self.pending()
            if max_items is not None:
                items = items[:max_items]
            for item in items:
                payload = {"action_id": item.action_id}
                self.audit.append(
                    "queued_action_attempted",
                    item.action.target,
                    payload,
                    timestamp=timestamp,
                )
                try:
                    handler(item)
                except Exception as error:  # noqa: BLE001 - device adapters vary
                    message = str(error).replace("\n", " ")[:200]
                    self.audit.append(
                        "queued_action_failed",
                        item.action.target,
                        {**payload, "error": message, "error_type": type(error).__name__},
                        timestamp=timestamp,
                    )
                    failed.append(item.action_id)
                    continue
                self.audit.append(
                    "queued_action_completed",
                    item.action.target,
                    payload,
                    timestamp=timestamp,
                )
                completed.append(item.action_id)
        return DispatchReport(len(completed) + len(failed), tuple(completed), tuple(failed))

    def _known_ids(self) -> set[str]:
        identifiers: set[str] = set()
        for entry in self.audit.read(kind="queued_action_created"):
            identifier = entry.payload.get("action_id")
            if isinstance(identifier, str):
                identifiers.add(identifier)
        return identifiers
