"""Append-only local audit log for sensor events and automation actions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

        entry = AuditEntry(
            timestamp=timestamp or datetime.now(timezone.utc),
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
        if not self.path.exists():
            return []

        entries: list[AuditEntry] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    entry = AuditEntry(
                        timestamp=datetime.fromisoformat(raw["timestamp"]),
                        kind=str(raw["kind"]),
                        source=str(raw["source"]),
                        payload=dict(raw["payload"]),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise AuditLogCorrupted(self.path, line_number) from error

                if kind is not None and entry.kind != kind:
                    continue
                if since is not None and entry.timestamp < since:
                    continue
                entries.append(entry)

        return entries[-limit:] if limit is not None else entries
