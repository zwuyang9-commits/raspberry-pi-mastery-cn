"""Verified local backups for Raspberry Pi state and configuration files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "manifest.json"
FORMAT_VERSION = 1


class BackupError(ValueError):
    """Raised when an archive is invalid or cannot be restored safely."""


@dataclass(frozen=True)
class BackupFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BackupReport:
    archive: Path
    created_at: datetime
    files: tuple[BackupFile, ...]

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.files)


@dataclass(frozen=True)
class RestoreDrillReport:
    """Evidence that an archive was verified and restored into an isolated directory."""

    archive: Path
    checked_at: datetime
    files: tuple[BackupFile, ...]

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.files)


@dataclass(frozen=True)
class BackupRotationPlan:
    """A reviewable retention plan; invalid archives are never removal candidates."""

    keep: tuple[Path, ...]
    remove: tuple[Path, ...]
    invalid: tuple[Path, ...]
    applied: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError(f"unsafe backup path: {value}")
    return path


def _safe_restore_path(root: Path, relative: PurePosixPath) -> Path:
    """Reject existing symlinks anywhere below a restore destination."""

    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise BackupError(f"restore target contains a symbolic link: {candidate}")
    return candidate


class LocalBackupManager:
    """Creates, verifies and restores portable ZIP backups."""

    def __init__(self, source_root: str | Path) -> None:
        self.source_root = Path(source_root).resolve()

    def create(
        self,
        archive: str | Path,
        paths: Iterable[str | Path],
        *,
        created_at: datetime | None = None,
    ) -> BackupReport:
        archive_path = Path(archive).resolve()
        selected = self._collect(paths)
        if not selected:
            raise BackupError("backup must contain at least one file")

        timestamp = created_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        files = tuple(
            BackupFile(
                path=path.relative_to(self.source_root).as_posix(),
                size=path.stat().st_size,
                sha256=_sha256(path),
            )
            for path in selected
        )
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": timestamp.isoformat(),
            "files": [item.__dict__ for item in files],
        }

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive_path.with_name(f".{archive_path.name}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for source, item in zip(selected, files, strict=True):
                    bundle.write(source, item.path)
                bundle.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                )
            os.replace(temporary, archive_path)
        finally:
            temporary.unlink(missing_ok=True)
        return BackupReport(archive_path, timestamp, files)

    def verify(self, archive: str | Path) -> BackupReport:
        archive_path = Path(archive).resolve()
        try:
            with zipfile.ZipFile(archive_path) as bundle:
                manifest = self._read_manifest(bundle)
                expected_names = {item.path for item in manifest.files} | {MANIFEST_NAME}
                actual_names = set(bundle.namelist())
                if actual_names != expected_names:
                    raise BackupError("archive contents do not match manifest")
                for item in manifest.files:
                    content = bundle.read(item.path)
                    if len(content) != item.size:
                        raise BackupError(f"size mismatch: {item.path}")
                    if hashlib.sha256(content).hexdigest() != item.sha256:
                        raise BackupError(f"checksum mismatch: {item.path}")
                return BackupReport(archive_path, manifest.created_at, manifest.files)
        except (OSError, zipfile.BadZipFile, KeyError) as error:
            raise BackupError(f"invalid backup archive: {archive_path}") from error

    def restore(
        self,
        archive: str | Path,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> tuple[Path, ...]:
        report = self.verify(archive)
        requested_root = Path(destination)
        if requested_root.is_symlink():
            raise BackupError(f"restore destination is a symbolic link: {requested_root}")
        target_root = requested_root.resolve()
        targets = [
            _safe_restore_path(target_root, _safe_relative_path(item.path))
            for item in report.files
        ]
        invalid_targets = [path for path in targets if path.exists() and not path.is_file()]
        if invalid_targets:
            raise BackupError(f"restore target is not a regular file: {invalid_targets[0]}")
        conflicts = [path for path in targets if path.exists()]
        if conflicts and not overwrite:
            raise BackupError(f"restore target already exists: {conflicts[0]}")

        target_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="rpi-backup-", dir=target_root))
        rollback = Path(tempfile.mkdtemp(prefix="rpi-rollback-", dir=target_root))
        restored: list[Path] = []
        applied: list[tuple[Path, Path | None]] = []
        try:
            with zipfile.ZipFile(report.archive) as bundle:
                for item in report.files:
                    relative = _safe_relative_path(item.path)
                    staged = stage.joinpath(*relative.parts)
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item.path) as source, staged.open("wb") as output:
                        shutil.copyfileobj(source, output)
            for item in report.files:
                relative = _safe_relative_path(item.path)
                staged = stage.joinpath(*relative.parts)
                final = _safe_restore_path(target_root, relative)
                final.parent.mkdir(parents=True, exist_ok=True)
                final = _safe_restore_path(target_root, relative)
                previous: Path | None = None
                if final.exists():
                    previous = rollback.joinpath(*relative.parts)
                    previous.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final, previous)
                applied.append((final, previous))
                os.replace(staged, final)
                restored.append(final)
        except (BackupError, OSError) as error:
            rollback_failure: OSError | None = None
            for final, previous in reversed(applied):
                try:
                    final.unlink(missing_ok=True)
                    if previous is not None and previous.exists():
                        final.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(previous, final)
                except OSError as rollback_error:
                    rollback_failure = rollback_error
            if rollback_failure is not None:
                raise BackupError("restore failed and rollback was incomplete") from rollback_failure
            raise BackupError("restore failed; previous files were restored") from error
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(rollback, ignore_errors=True)
        return tuple(restored)

    def drill(self, archive: str | Path) -> RestoreDrillReport:
        """Perform a disposable restore and verify every extracted file again."""

        report = self.verify(archive)
        with tempfile.TemporaryDirectory(prefix="rpi-restore-drill-") as directory:
            destination = Path(directory)
            restored = self.restore(report.archive, destination)
            if len(restored) != len(report.files):
                raise BackupError("restore drill produced an unexpected file count")
            for item in report.files:
                restored_file = destination.joinpath(*PurePosixPath(item.path).parts)
                if restored_file.stat().st_size != item.size or _sha256(restored_file) != item.sha256:
                    raise BackupError(f"restore drill verification failed: {item.path}")

        return RestoreDrillReport(
            archive=report.archive,
            checked_at=datetime.now(timezone.utc),
            files=report.files,
        )

    def rotate(
        self,
        directory: str | Path,
        *,
        keep: int,
        apply: bool = False,
    ) -> BackupRotationPlan:
        """Keep the newest verified archives and optionally remove older ones."""

        if keep < 1:
            raise ValueError("keep must be positive")
        backup_directory = Path(directory).resolve()
        if not backup_directory.exists():
            return BackupRotationPlan((), (), (), apply)
        if not backup_directory.is_dir():
            raise BackupError(f"backup directory is not a directory: {backup_directory}")

        verified: list[BackupReport] = []
        invalid: list[Path] = []
        for archive in sorted(backup_directory.glob("*.zip")):
            try:
                verified.append(self.verify(archive))
            except BackupError:
                invalid.append(archive)
        verified.sort(key=lambda report: (report.created_at, report.archive.name), reverse=True)
        retained = tuple(report.archive for report in verified[:keep])
        removal = tuple(report.archive for report in verified[keep:])
        if apply:
            for archive in removal:
                archive.unlink()
        return BackupRotationPlan(retained, removal, tuple(invalid), apply)

    def _collect(self, paths: Iterable[str | Path]) -> list[Path]:
        collected: set[Path] = set()
        for value in paths:
            candidate = (self.source_root / value).resolve()
            if not candidate.is_relative_to(self.source_root):
                raise BackupError(f"path is outside source root: {value}")
            if not candidate.exists():
                raise BackupError(f"backup source does not exist: {value}")
            if candidate.is_symlink():
                raise BackupError(f"symbolic links are not supported: {value}")
            if candidate.is_file():
                collected.add(candidate)
            else:
                for child in candidate.rglob("*"):
                    if child.is_symlink():
                        raise BackupError(f"symbolic links are not supported: {child}")
                    if child.is_file():
                        collected.add(child.resolve())
        return sorted(collected, key=lambda path: path.relative_to(self.source_root).as_posix())

    @staticmethod
    def _read_manifest(bundle: zipfile.ZipFile) -> BackupReport:
        try:
            raw: Any = json.loads(bundle.read(MANIFEST_NAME))
            if raw.get("format_version") != FORMAT_VERSION or not isinstance(raw.get("files"), list):
                raise BackupError("unsupported backup manifest")
            created_at = datetime.fromisoformat(raw["created_at"])
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise BackupError("manifest timestamp must include a timezone")
            files = tuple(
                BackupFile(
                    path=str(item["path"]),
                    size=int(item["size"]),
                    sha256=str(item["sha256"]),
                )
                for item in raw["files"]
            )
            if not files or len({item.path for item in files}) != len(files):
                raise BackupError("manifest contains no files or duplicate paths")
            for item in files:
                _safe_relative_path(item.path)
                if (
                    item.size < 0
                    or len(item.sha256) != 64
                    or any(character not in "0123456789abcdef" for character in item.sha256)
                ):
                    raise BackupError(f"invalid manifest entry: {item.path}")
            return BackupReport(Path(), created_at, files)
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise BackupError("invalid backup manifest") from error
