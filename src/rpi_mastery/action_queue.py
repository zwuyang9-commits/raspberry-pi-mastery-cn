"""Durable at-least-once queue for local automation actions."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .audit import (
    AuditArchiveReport,
    AuditEntry,
    AuditLog,
    _as_utc,
    _exclusive_file_lock,
)
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
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None


@dataclass(frozen=True)
class DispatchReport:
    processed: int
    completed: tuple[str, ...]
    failed: tuple[str, ...]
    dead_lettered: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()
    leased: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueStatus:
    pending: int
    ready: int
    deferred: int
    leased: int
    dead_letters: int
    next_ready_at: datetime | None


class DurableActionQueue:
    """Reconstructs pending work from an append-only audit log after restarts."""

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit
        self._lock = RLock()
        self._lock_path = audit.path.with_name(f".{audit.path.name}.queue.lock")

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

        with self._lock, _exclusive_file_lock(self._lock_path):
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
                    raw_lease_expiry = entry.payload.get("lease_expires_at")
                    try:
                        lease_expires_at = (
                            datetime.fromisoformat(raw_lease_expiry)
                            if isinstance(raw_lease_expiry, str)
                            else entry.timestamp
                        )
                    except ValueError as error:
                        raise ActionQueueError(f"invalid lease expiry: {identifier}") from error
                    if lease_expires_at.tzinfo is None:
                        raise ActionQueueError(f"lease expiry has no timezone: {identifier}")
                    active[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts + 1,
                        last_error=item.last_error,
                        next_attempt_at=item.next_attempt_at,
                        lease_expires_at=lease_expires_at,
                    )
                elif entry.kind == "queued_action_failed" and identifier in active:
                    item = active[identifier]
                    raw_next_attempt = entry.payload.get("next_attempt_at")
                    try:
                        next_attempt_at = (
                            datetime.fromisoformat(raw_next_attempt)
                            if isinstance(raw_next_attempt, str)
                            else None
                        )
                    except ValueError as error:
                        raise ActionQueueError(
                            f"invalid next attempt time: {identifier}"
                        ) from error
                    if next_attempt_at is not None and next_attempt_at.tzinfo is None:
                        raise ActionQueueError(f"next attempt time has no timezone: {identifier}")
                    active[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts,
                        last_error=str(entry.payload.get("error", "unknown error")),
                        next_attempt_at=next_attempt_at,
                        lease_expires_at=None,
                    )
                elif entry.kind in {
                    "queued_action_completed",
                    "queued_action_dead_lettered",
                    "queued_action_cancelled",
                }:
                    active.pop(identifier, None)
            return tuple(active[identifier] for identifier in order if identifier in active)

    def dead_letters(self) -> tuple[QueuedAction, ...]:
        """Return actions removed after exhausting their retry allowance."""

        with self._lock:
            known: dict[str, QueuedAction] = {}
            dead: dict[str, QueuedAction] = {}
            order: list[str] = []
            for entry in self.audit.read():
                identifier = entry.payload.get("action_id")
                if not isinstance(identifier, str):
                    continue
                if entry.kind == "queued_action_created":
                    try:
                        action = Action(
                            entry.source,
                            str(entry.payload["command"]),
                            entry.payload["value"],
                            str(entry.payload["reason"]),
                        )
                    except KeyError as error:
                        raise ActionQueueError(f"invalid queued action: {identifier}") from error
                    known[identifier] = QueuedAction(identifier, action, entry.timestamp)
                elif entry.kind == "queued_action_attempted" and identifier in known:
                    item = known[identifier]
                    raw_lease_expiry = entry.payload.get("lease_expires_at")
                    try:
                        lease_expires_at = (
                            datetime.fromisoformat(raw_lease_expiry)
                            if isinstance(raw_lease_expiry, str)
                            else entry.timestamp
                        )
                    except ValueError as error:
                        raise ActionQueueError(f"invalid lease expiry: {identifier}") from error
                    known[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts + 1,
                        last_error=item.last_error,
                        next_attempt_at=item.next_attempt_at,
                        lease_expires_at=lease_expires_at,
                    )
                elif entry.kind == "queued_action_failed" and identifier in known:
                    item = known[identifier]
                    raw_next_attempt = entry.payload.get("next_attempt_at")
                    try:
                        next_attempt_at = (
                            datetime.fromisoformat(raw_next_attempt)
                            if isinstance(raw_next_attempt, str)
                            else None
                        )
                    except ValueError as error:
                        raise ActionQueueError(
                            f"invalid next attempt time: {identifier}"
                        ) from error
                    known[identifier] = QueuedAction(
                        item.action_id,
                        item.action,
                        item.enqueued_at,
                        attempts=item.attempts,
                        last_error=str(entry.payload.get("error", "unknown error")),
                        next_attempt_at=next_attempt_at,
                        lease_expires_at=None,
                    )
                elif entry.kind == "queued_action_dead_lettered" and identifier in known:
                    dead[identifier] = known[identifier]
                    order.append(identifier)
            return tuple(dead[identifier] for identifier in order)

    def requeue_dead_letter(
        self,
        action_id: str,
        *,
        new_action_id: str | None = None,
        now: datetime | None = None,
    ) -> QueuedAction:
        with self._lock:
            item = next(
                (candidate for candidate in self.dead_letters() if candidate.action_id == action_id),
                None,
            )
            if item is None:
                raise ActionQueueError(f"dead letter not found: {action_id}")
            return self.enqueue(item.action, action_id=new_action_id, now=now)

    def cancel(
        self,
        action_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        """Cancel pending work while preserving an auditable terminal record."""

        if not reason.strip():
            raise ValueError("cancellation reason cannot be empty")
        with self._lock, _exclusive_file_lock(self._lock_path):
            item = next(
                (candidate for candidate in self.pending() if candidate.action_id == action_id),
                None,
            )
            if item is None:
                raise ActionQueueError(f"pending action not found: {action_id}")
            self.audit.append(
                "queued_action_cancelled",
                item.action.target,
                {"action_id": action_id, "reason": reason.strip()},
                timestamp=now,
            )

    def archive_terminal_before(
        self,
        cutoff: datetime,
        archive: str | Path,
        *,
        apply: bool = False,
    ) -> AuditArchiveReport:
        """Archive complete terminal lifecycles and retain ID tombstones."""

        cutoff_utc = _as_utc(cutoff)
        archive_path = Path(archive)
        with self._lock, _exclusive_file_lock(self._lock_path):  # noqa: SIM117
            with _exclusive_file_lock(self.audit._lock_path):
                entries = self.audit.read()
                terminal: dict[str, AuditEntry] = {}
                for entry in entries:
                    identifier = entry.payload.get("action_id")
                    if (
                        isinstance(identifier, str)
                        and entry.kind
                        in {"queued_action_completed", "queued_action_cancelled"}
                    ):
                        terminal[identifier] = entry
                identifiers = {
                    identifier
                    for identifier, entry in terminal.items()
                    if entry.timestamp < cutoff_utc
                }
                archived = [
                    entry
                    for entry in entries
                    if entry.kind.startswith("queued_action_")
                    and entry.payload.get("action_id") in identifiers
                ]
                retained = [entry for entry in entries if entry not in archived]
                for identifier in sorted(identifiers):
                    terminal_entry = terminal[identifier]
                    retained.append(
                        AuditEntry(
                            terminal_entry.timestamp,
                            "queued_action_archived",
                            terminal_entry.source,
                            {
                                "action_id": identifier,
                                "terminal_kind": terminal_entry.kind,
                            },
                        )
                    )
                return self.audit._archive_partition(
                    archive_path,
                    archived,
                    retained,
                    apply=apply,
                )

    def status(self, *, now: datetime | None = None) -> QueueStatus:
        """Return an operational summary without mutating queue state."""

        timestamp = _as_utc(now or datetime.now(timezone.utc))
        items = self.pending()
        ready = 0
        deferred = 0
        leased = 0
        availability: list[datetime] = []
        for item in items:
            blockers = [
                value
                for value in (item.next_attempt_at, item.lease_expires_at)
                if value is not None and value > timestamp
            ]
            if item.lease_expires_at is not None and item.lease_expires_at > timestamp:
                leased += 1
            elif item.next_attempt_at is not None and item.next_attempt_at > timestamp:
                deferred += 1
            else:
                ready += 1
            if blockers:
                availability.append(max(blockers))
        return QueueStatus(
            pending=len(items),
            ready=ready,
            deferred=deferred,
            leased=leased,
            dead_letters=len(self.dead_letters()),
            next_ready_at=min(availability) if availability else None,
        )

    def dispatch(
        self,
        handler: Callable[[QueuedAction], None],
        *,
        max_items: int | None = None,
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(0),
        lease_duration: timedelta = timedelta(seconds=30),
        now: datetime | None = None,
    ) -> DispatchReport:
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        timestamp = _as_utc(now or datetime.now(timezone.utc))
        completed: list[str] = []
        failed: list[str] = []
        dead_lettered: list[str] = []
        deferred: list[str] = []
        leased: list[str] = []
        with self._lock, _exclusive_file_lock(self._lock_path):
            items = self.pending()
            if max_items is not None:
                items = items[:max_items]
            for item in items:
                if item.lease_expires_at is not None and timestamp < item.lease_expires_at:
                    leased.append(item.action_id)
                    continue
                if item.next_attempt_at is not None and timestamp < item.next_attempt_at:
                    deferred.append(item.action_id)
                    continue
                payload = {"action_id": item.action_id}
                self.audit.append(
                    "queued_action_attempted",
                    item.action.target,
                    {
                        **payload,
                        "lease_expires_at": (timestamp + lease_duration).isoformat(),
                    },
                    timestamp=timestamp,
                )
                try:
                    handler(item)
                except Exception as error:  # noqa: BLE001 - device adapters vary
                    message = str(error).replace("\n", " ")[:200]
                    next_attempt_at = timestamp + retry_delay * (2**item.attempts)
                    self.audit.append(
                        "queued_action_failed",
                        item.action.target,
                        {
                            **payload,
                            "error": message,
                            "error_type": type(error).__name__,
                            "next_attempt_at": next_attempt_at.isoformat(),
                        },
                        timestamp=timestamp,
                    )
                    failed.append(item.action_id)
                    if item.attempts + 1 >= max_attempts:
                        self.audit.append(
                            "queued_action_dead_lettered",
                            item.action.target,
                            {**payload, "attempts": item.attempts + 1},
                            timestamp=timestamp,
                        )
                        dead_lettered.append(item.action_id)
                    continue
                self.audit.append(
                    "queued_action_completed",
                    item.action.target,
                    payload,
                    timestamp=timestamp,
                )
                completed.append(item.action_id)
        return DispatchReport(
            len(completed) + len(failed),
            tuple(completed),
            tuple(failed),
            tuple(dead_lettered),
            tuple(deferred),
            tuple(leased),
        )

    def _known_ids(self) -> set[str]:
        identifiers: set[str] = set()
        for entry in self.audit.read():
            if entry.kind not in {"queued_action_created", "queued_action_archived"}:
                continue
            identifier = entry.payload.get("action_id")
            if isinstance(identifier, str):
                identifiers.add(identifier)
        return identifiers
