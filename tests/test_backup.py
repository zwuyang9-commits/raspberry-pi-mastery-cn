import json
import zipfile
from datetime import datetime, timezone

import pytest

from rpi_mastery.backup import BackupError, LocalBackupManager

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def test_create_verify_and_restore_backup(tmp_path):
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    (source / "data" / "environment.csv").write_text("temperature\n23.5\n", encoding="utf-8")
    (source / "state.jsonl").write_text('{"status":"ok"}\n', encoding="utf-8")
    manager = LocalBackupManager(source)

    report = manager.create(tmp_path / "backup.zip", ["data", "state.jsonl"], created_at=NOW)

    assert [item.path for item in report.files] == ["data/environment.csv", "state.jsonl"]
    assert report.total_size > 0
    assert manager.verify(report.archive).files == report.files

    restored = manager.restore(report.archive, tmp_path / "restored")
    assert len(restored) == 2
    assert (tmp_path / "restored" / "data" / "environment.csv").read_text(encoding="utf-8") == "temperature\n23.5\n"


def test_verify_rejects_modified_payload(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.txt").write_text("original", encoding="utf-8")
    manager = LocalBackupManager(source)
    archive = manager.create(tmp_path / "backup.zip", ["state.txt"]).archive

    replacement = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(replacement, "w") as changed:
        for name in original.namelist():
            content = b"tampered" if name == "state.txt" else original.read(name)
            changed.writestr(name, content)
    replacement.replace(archive)

    with pytest.raises(BackupError, match="contents do not match|checksum mismatch"):
        manager.verify(archive)


def test_restore_requires_explicit_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_text('{"enabled":true}', encoding="utf-8")
    manager = LocalBackupManager(source)
    archive = manager.create(tmp_path / "backup.zip", ["config.json"]).archive
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "config.json").write_text("old", encoding="utf-8")

    with pytest.raises(BackupError, match="already exists"):
        manager.restore(archive, destination)

    manager.restore(archive, destination, overwrite=True)
    assert json.loads((destination / "config.json").read_text(encoding="utf-8")) == {"enabled": True}


def test_restore_drill_extracts_and_rechecks_without_touching_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    state = source / "state.json"
    state.write_text('{"healthy":true}', encoding="utf-8")
    manager = LocalBackupManager(source)
    archive = manager.create(tmp_path / "backup.zip", ["state.json"]).archive

    report = manager.drill(archive)

    assert report.archive == archive
    assert report.total_size == state.stat().st_size
    assert report.checked_at.tzinfo == timezone.utc
    assert state.read_text(encoding="utf-8") == '{"healthy":true}'


def test_create_rejects_path_outside_source_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(BackupError, match="outside source root"):
        LocalBackupManager(source).create(tmp_path / "backup.zip", [outside])


def test_rotation_previews_then_removes_only_verified_old_backups(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    state = source / "state.txt"
    state.write_text("state", encoding="utf-8")
    backups = tmp_path / "backups"
    manager = LocalBackupManager(source)
    for day in range(1, 4):
        manager.create(
            backups / f"state-{day}.zip",
            ["state.txt"],
            created_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        )
    invalid = backups / "unrelated.zip"
    invalid.write_bytes(b"not a zip")

    preview = manager.rotate(backups, keep=2)

    assert [path.name for path in preview.keep] == ["state-3.zip", "state-2.zip"]
    assert [path.name for path in preview.remove] == ["state-1.zip"]
    assert preview.invalid == (invalid,)
    assert all(path.exists() for path in preview.remove)

    applied = manager.rotate(backups, keep=2, apply=True)
    assert applied.applied is True
    assert not (backups / "state-1.zip").exists()
    assert invalid.exists()


def test_rotation_rejects_zero_retention(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        LocalBackupManager(tmp_path).rotate(tmp_path, keep=0)
