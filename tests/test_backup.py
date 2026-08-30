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


def test_create_rejects_path_outside_source_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(BackupError, match="outside source root"):
        LocalBackupManager(source).create(tmp_path / "backup.zip", [outside])
