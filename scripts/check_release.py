"""Validate release metadata before a package or tag is published."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib


def package_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def module_version(root: Path) -> str:
    source = (root / "src" / "rpi_mastery" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ValueError("src/rpi_mastery/__init__.py does not define a literal __version__")


def validate_release(root: Path, tag: str | None = None) -> str:
    project_version = package_version(root)
    public_version = module_version(root)
    if public_version != project_version:
        raise ValueError(
            f"version mismatch: pyproject.toml={project_version}, __init__.py={public_version}"
        )

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {project_version}" not in changelog:
        raise ValueError(f"CHANGELOG.md has no section for version {project_version}")

    if tag is not None:
        expected_tag = f"v{project_version}"
        if tag != expected_tag:
            raise ValueError(f"tag mismatch: expected {expected_tag}, got {tag}")

    return project_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", help="Git tag to compare with the package version")
    args = parser.parse_args()

    try:
        version = validate_release(args.root.resolve(), args.tag)
    except (KeyError, OSError, SyntaxError, TypeError, ValueError) as error:
        print(f"release metadata check failed: {error}", file=sys.stderr)
        return 1

    print(f"release metadata is consistent for {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
