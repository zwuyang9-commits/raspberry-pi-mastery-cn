from pathlib import Path

import pytest

from scripts.check_release import validate_release


def write_release_files(root: Path, *, project: str = "1.2.3", public: str = "1.2.3") -> None:
    (root / "src" / "rpi_mastery").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "rpi-mastery"\nversion = "{project}"\n', encoding="utf-8"
    )
    (root / "src" / "rpi_mastery" / "__init__.py").write_text(
        f'__version__ = "{public}"\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(f"# Changes\n\n## {project}\n", encoding="utf-8")


def test_release_metadata_matches(tmp_path: Path) -> None:
    write_release_files(tmp_path)

    assert validate_release(tmp_path) == "1.2.3"
    assert validate_release(tmp_path, "v1.2.3") == "1.2.3"


def test_release_metadata_rejects_public_version_mismatch(tmp_path: Path) -> None:
    write_release_files(tmp_path, public="1.2.4")

    with pytest.raises(ValueError, match="version mismatch"):
        validate_release(tmp_path)


def test_release_metadata_rejects_tag_mismatch(tmp_path: Path) -> None:
    write_release_files(tmp_path)

    with pytest.raises(ValueError, match="tag mismatch"):
        validate_release(tmp_path, "v1.2.4")


def test_release_metadata_requires_changelog_section(tmp_path: Path) -> None:
    write_release_files(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("# Changes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no section"):
        validate_release(tmp_path)
