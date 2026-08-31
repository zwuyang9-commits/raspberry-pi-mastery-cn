"""Deployment preflight checks for the local Raspberry Pi services."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path


class DeploymentConfigError(ValueError):
    """Raised when a service configuration is unsafe or invalid."""


def api_token_issue(token: str) -> str | None:
    """Return a safe diagnostic when an API token cannot be used securely."""

    if len(token) < 16:
        return "RPI_API_TOKEN must be at least 16 characters"
    if any(ord(character) < 33 or ord(character) > 126 for character in token):
        return "RPI_API_TOKEN must use printable ASCII without spaces"
    return None


@dataclass(frozen=True)
class DeploymentCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DeploymentConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str | None = None
    audit_log: Path | None = None
    queue_log: Path | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DeploymentConfig:
        values = os.environ if environ is None else environ
        raw_port = values.get("RPI_API_PORT", "8000")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise DeploymentConfigError(f"RPI_API_PORT is not an integer: {raw_port}") from error

        return cls(
            host=values.get("RPI_API_HOST", "127.0.0.1"),
            port=port,
            api_token=values.get("RPI_API_TOKEN") or None,
            audit_log=_optional_path(values.get("RPI_API_AUDIT_LOG")),
            queue_log=_optional_path(values.get("RPI_QUEUE_LOG")),
        )

    def check(self) -> tuple[DeploymentCheck, ...]:
        checks = [self._check_port(), self._check_access(), self._check_state_paths()]
        return tuple(checks)

    def require_safe(self) -> tuple[DeploymentCheck, ...]:
        checks = self.check()
        failures = [check.detail for check in checks if not check.passed]
        if failures:
            raise DeploymentConfigError("; ".join(failures))
        return checks

    def _check_port(self) -> DeploymentCheck:
        passed = 1 <= self.port <= 65535
        detail = f"port {self.port} is valid" if passed else f"port must be 1..65535: {self.port}"
        return DeploymentCheck("port", passed, detail)

    def _check_access(self) -> DeploymentCheck:
        host = self.host.strip()
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"

        if self.api_token is not None and (issue := api_token_issue(self.api_token)) is not None:
            return DeploymentCheck("write-access", False, issue)
        if not loopback and self.api_token is None:
            return DeploymentCheck(
                "write-access",
                False,
                f"RPI_API_TOKEN is required when listening on non-loopback host {host!r}",
            )
        mode = "token-protected" if self.api_token else "loopback-only"
        return DeploymentCheck("write-access", True, f"write access is {mode}")

    def _check_state_paths(self) -> DeploymentCheck:
        configured = [path.resolve() for path in (self.audit_log, self.queue_log) if path is not None]
        if len(configured) != len(set(configured)):
            return DeploymentCheck("state-paths", False, "audit and queue logs must use different paths")

        for path in configured:
            if path.exists():
                if not path.is_file() or not os.access(path, os.W_OK):
                    return DeploymentCheck(
                        "state-paths", False, f"state file is not writable: {path}"
                    )
                continue
            ancestor = path.parent
            while not ancestor.exists() and ancestor != ancestor.parent:
                ancestor = ancestor.parent
            if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
                return DeploymentCheck(
                    "state-paths", False, f"state directory is not writable: {path.parent}"
                )
        return DeploymentCheck("state-paths", True, f"validated {len(configured)} state paths")


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None
