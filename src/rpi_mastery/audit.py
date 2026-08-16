"""Append-only local audit log for sensor events and automation actions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _as_utc(value: datetime) -> datetime:
    """Return a datetime that is safe to compare with other audit timestamps."""

    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class AuditEntry:
    timestamp: datetime
    kind: str
    source: str
    payload: dict[str, Any]


class AuditLogCorrupted(ValueError):
    """Raised when a JSONL record cannot be decoded safely."""

    def __init__(self, path: Path, line_number: int) -> None:
        super().__init__(f"invalid audit record at {path}:{line_number}")
        self.path = path
        self.line_number = line_number


class AuditLog:
    """Durable JSONL log that can be inspected without a database server."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(
        self,
        kind: str,
        source: str,
        payload: dict[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> AuditEntry:
        if not kind.strip():
            raise ValueError("kind cannot be empty")
        if not source.strip():
            raise ValueError("source cannot be empty")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")

        entry = AuditEntry(
            timestamp=_as_utc(
                timestamp if timestamp is not None else datetime.now(timezone.utc)
            ),
            kind=kind,
            source=source,
            payload=dict(payload),
        )
        encoded = {
            **asdict(entry),
            "timestamp": entry.timestamp.isoformat(),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(encoded, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def read(
        self,
        *,
        kind: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        since_utc = _as_utc(since) if since is not None else None
        if not self.path.exists():
            return []

        entries: list[AuditEntry] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise TypeError("audit record must be a JSON object")

                    raw_timestamp = raw["timestamp"]
                    raw_kind = raw["kind"]
                    raw_source = raw["source"]
                    raw_payload = raw["payload"]
                    if not isinstance(raw_timestamp, str):
                        raise TypeError("timestamp must be a string")
                    if not isinstance(raw_kind, str) or not raw_kind.strip():
                        raise TypeError("kind must be a non-empty string")
                    if not isinstance(raw_source, str) or not raw_source.strip():
                        raise TypeError("source must be a non-empty string")
                    if not isinstance(raw_payload, dict):
                        raise TypeError("payload must be a JSON object")

                    entry = AuditEntry(
                        timestamp=_as_utc(datetime.fromisoformat(raw_timestamp)),
                        kind=raw_kind,
                        source=raw_source,
                        payload=dict(raw_payload),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise AuditLogCorrupted(self.path, line_number) from error

                if kind is not None and entry.kind != kind:
                    continue
                if since_utc is not None and entry.timestamp < since_utc:
                    continue
                entries.append(entry)

        return entries[-limit:] if limit is not None else entries
