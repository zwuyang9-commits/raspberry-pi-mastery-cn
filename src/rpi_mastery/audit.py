"""Append-only local audit log for sensor events and automation actions."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@contextmanager
def _exclusive_file_lock(path: Path):
    """Hold a cross-process lock that the OS releases if the writer exits."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


@dataclass(frozen=True)
class AuditSummary:
    entries: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    kinds: dict[str, int]
    sources: dict[str, int]


@dataclass(frozen=True)
class AuditArchiveReport:
    source: Path
    archive: Path
    archived_entries: int
    retained_entries: int
    applied: bool


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
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

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

        with _exclusive_file_lock(self._lock_path):
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
        source: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        since_utc = _as_utc(since) if since is not None else None
        until_utc = _as_utc(until) if until is not None else None
        if since_utc is not None and until_utc is not None and since_utc > until_utc:
            raise ValueError("since cannot be later than until")
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
                if source is not None and entry.source != source:
                    continue
                if since_utc is not None and entry.timestamp < since_utc:
                    continue
                if until_utc is not None and entry.timestamp > until_utc:
                    continue
                entries.append(entry)

        return entries[-limit:] if limit is not None else entries

    def summarize(
        self,
        *,
        kind: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AuditSummary:
        entries = self.read(kind=kind, source=source, since=since, until=until)
        kinds: dict[str, int] = {}
        sources: dict[str, int] = {}
        for entry in entries:
            kinds[entry.kind] = kinds.get(entry.kind, 0) + 1
            sources[entry.source] = sources.get(entry.source, 0) + 1
        return AuditSummary(
            entries=len(entries),
            first_timestamp=entries[0].timestamp if entries else None,
            last_timestamp=entries[-1].timestamp if entries else None,
            kinds=dict(sorted(kinds.items())),
            sources=dict(sorted(sources.items())),
        )

    def archive_before(
        self,
        cutoff: datetime,
        archive: str | Path,
        *,
        apply: bool = False,
    ) -> AuditArchiveReport:
        """Preview or atomically archive records older than a UTC-normalized cutoff."""

        cutoff_utc = _as_utc(cutoff)
        archive_path = Path(archive).resolve()
        source_path = self.path.resolve()
        if archive_path == source_path:
            raise ValueError("archive path must differ from source log")
        with _exclusive_file_lock(self._lock_path):
            entries = self.read()
            if any(entry.kind.startswith("queued_action_") for entry in entries):
                raise ValueError(
                    "generic archival cannot split durable queue lifecycle records"
                )
            archived = [entry for entry in entries if entry.timestamp < cutoff_utc]
            retained = [entry for entry in entries if entry.timestamp >= cutoff_utc]
            return self._archive_partition(archive_path, archived, retained, apply=apply)

    def _archive_partition(
        self,
        archive_path: Path,
        archived: list[AuditEntry],
        retained: list[AuditEntry],
        *,
        apply: bool,
    ) -> AuditArchiveReport:
        """Atomically replace this log with a caller-validated partition."""

        source_path = self.path.resolve()
        archive_path = archive_path.resolve()
        if archive_path == source_path:
            raise ValueError("archive path must differ from source log")
        report = AuditArchiveReport(
            source=source_path,
            archive=archive_path,
            archived_entries=len(archived),
            retained_entries=len(retained),
            applied=apply,
        )
        if not apply or not archived:
            return report
        if archive_path.exists():
            raise FileExistsError(f"archive already exists: {archive_path}")

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        archive_temporary = archive_path.with_name(f".{archive_path.name}.tmp")
        source_temporary = source_path.with_name(f".{source_path.name}.retained.tmp")
        try:
            self._write_entries(archive_temporary, archived)
            self._write_entries(source_temporary, retained)
            os.replace(archive_temporary, archive_path)
            os.replace(source_temporary, source_path)
        finally:
            archive_temporary.unlink(missing_ok=True)
            source_temporary.unlink(missing_ok=True)
        return report

    @staticmethod
    def _write_entries(path: Path, entries: list[AuditEntry]) -> None:
        with path.open("x", encoding="utf-8") as handle:
            for entry in entries:
                encoded = {
                    **asdict(entry),
                    "timestamp": entry.timestamp.isoformat(),
                }
                handle.write(
                    json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
