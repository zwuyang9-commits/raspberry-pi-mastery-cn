import json
from pathlib import Path

import pytest

from scripts.artifact_manifest import verify_manifest, write_manifest


def prepare_release(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "rpi-mastery"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "rpi_mastery-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "rpi_mastery-1.2.3.tar.gz").write_bytes(b"sdist")
    return tmp_path, dist


def test_manifest_records_release_identity_and_checksums(tmp_path: Path) -> None:
    root, dist = prepare_release(tmp_path)

    manifest_path = write_manifest(dist, root, "abc123")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["project"] == "rpi-mastery"
    assert manifest["version"] == "1.2.3"
    assert manifest["commit"] == "abc123"
    assert [item["name"] for item in manifest["files"]] == [
        "rpi_mastery-1.2.3-py3-none-any.whl",
        "rpi_mastery-1.2.3.tar.gz",
    ]
    verify_manifest(dist, root, "abc123")


def test_manifest_detects_tampered_distribution(tmp_path: Path) -> None:
    root, dist = prepare_release(tmp_path)
    write_manifest(dist, root, "abc123")
    (dist / "rpi_mastery-1.2.3.tar.gz").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="does not match"):
        verify_manifest(dist, root, "abc123")


def test_manifest_rejects_unexpected_artifacts(tmp_path: Path) -> None:
    root, dist = prepare_release(tmp_path)
    (dist / "old.whl").write_bytes(b"old")

    with pytest.raises(ValueError, match="exactly one"):
        write_manifest(dist, root, "abc123")


def test_manifest_rejects_wrong_distribution_version(tmp_path: Path) -> None:
    root, dist = prepare_release(tmp_path)
    (dist / "rpi_mastery-1.2.3.tar.gz").rename(dist / "rpi_mastery-9.9.9.tar.gz")

    with pytest.raises(ValueError, match="filename does not match"):
        write_manifest(dist, root, "abc123")
