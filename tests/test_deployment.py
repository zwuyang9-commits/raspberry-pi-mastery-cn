from pathlib import Path

import pytest

from rpi_mastery.deployment import DeploymentConfig, DeploymentConfigError


def test_default_deployment_is_safe_for_loopback() -> None:
    config = DeploymentConfig.from_env({})

    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert all(check.passed for check in config.require_safe())


def test_non_loopback_deployment_requires_token() -> None:
    config = DeploymentConfig.from_env({"RPI_API_HOST": "0.0.0.0"})

    with pytest.raises(DeploymentConfigError, match="TOKEN is required"):
        config.require_safe()


def test_non_loopback_deployment_accepts_strong_token() -> None:
    config = DeploymentConfig.from_env(
        {"RPI_API_HOST": "0.0.0.0", "RPI_API_TOKEN": "a-long-local-token"}
    )

    assert all(check.passed for check in config.require_safe())


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_port_is_rejected(port: str) -> None:
    with pytest.raises(DeploymentConfigError):
        DeploymentConfig.from_env({"RPI_API_PORT": port}).require_safe()


def test_state_logs_must_not_share_a_path(tmp_path: Path) -> None:
    shared = tmp_path / "state.jsonl"
    config = DeploymentConfig(audit_log=shared, queue_log=shared)

    with pytest.raises(DeploymentConfigError, match="different paths"):
        config.require_safe()


def test_state_log_must_not_be_a_directory(tmp_path: Path) -> None:
    state_directory = tmp_path / "state.jsonl"
    state_directory.mkdir()

    with pytest.raises(DeploymentConfigError, match="state file is not writable"):
        DeploymentConfig(audit_log=state_directory).require_safe()
