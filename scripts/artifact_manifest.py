"""Generate or verify deterministic checksums for built distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

MANIFEST_NAME = "artifact-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project(root: Path) -> tuple[str, str]:
    with (root / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    return str(project["name"]), str(project["version"])


def expected_manifest(dist: Path, root: Path, commit: str) -> dict[str, Any]:
    project, version = _project(root)
    artifacts = sorted(
        path for path in dist.iterdir() if path.is_file() and path.name != MANIFEST_NAME
    )
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
        raise ValueError("dist must contain exactly one wheel and one .tar.gz sdist")
    expected_prefix = f"{project.replace('-', '_')}-{version}"
    if any(not path.name.startswith(expected_prefix) for path in artifacts):
        raise ValueError(f"distribution filename does not match {project} {version}")
    return {
        "schema_version": 1,
        "project": project,
        "version": version,
        "commit": commit,
        "files": [
            {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}
            for path in artifacts
        ],
    }


def write_manifest(dist: Path, root: Path, commit: str) -> Path:
    manifest = expected_manifest(dist, root, commit)
    destination = dist / MANIFEST_NAME
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def verify_manifest(dist: Path, root: Path, commit: str) -> None:
    manifest_path = dist / MANIFEST_NAME
    actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = expected_manifest(dist, root, commit)
    if actual != expected:
        raise ValueError("artifact manifest does not match distributions or release metadata")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "verify"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--commit", default=os.getenv("GITHUB_SHA", "local"))
    args = parser.parse_args()

    try:
        if args.command == "generate":
            path = write_manifest(args.dist.resolve(), args.root.resolve(), args.commit)
            print(f"wrote artifact manifest: {path}")
        else:
            verify_manifest(args.dist.resolve(), args.root.resolve(), args.commit)
            print("artifact manifest verified")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"artifact manifest check failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
