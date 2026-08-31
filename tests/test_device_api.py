import importlib

from fastapi.testclient import TestClient

from rpi_mastery.audit import AuditLog
from rpi_mastery.hardware import SimulatedDigitalOutput

device_api = importlib.import_module("projects.03_local_device_api.main")


def test_token_protects_writes_and_output_closes_on_shutdown():
    output = SimulatedDigitalOutput()
    app = device_api.create_app(output=output, token="bench-secret")

    with TestClient(app) as client:
        denied = client.put("/output", json={"value": 0.5})
        assert denied.status_code == 401

        response = client.put(
            "/output",
            headers={"X-API-Token": "bench-secret"},
            json={"value": 0.5},
        )
        assert response.status_code == 200
        assert response.json() == {"value": 0.5}

    assert output.closed
    assert output.value == 0.0


def test_health_reports_write_protection_mode():
    app = device_api.create_app(token="bench-secret")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.json()["write_protection"] == "token"


def test_health_reports_explicit_hardware_mode():
    app = device_api.create_app(mode="hardware")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.json() == {
        "status": "ok",
        "mode": "hardware",
        "write_protection": "loopback-only",
    }


def test_readiness_probe_reports_ready() -> None:
    calls = []
    app = device_api.create_app(readiness_probe=lambda: calls.append("checked"))

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.json() == {"status": "ready", "mode": "simulated"}
    assert calls == ["checked"]


def test_readiness_probe_failure_returns_503_without_error_details() -> None:
    def unavailable() -> None:
        raise RuntimeError("internal hardware detail")

    app = device_api.create_app(readiness_probe=unavailable)
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "设备服务尚未就绪"}


def test_idempotency_key_replays_without_reapplying_output(tmp_path):
    class CountingOutput(SimulatedDigitalOutput):
        def __init__(self):
            super().__init__()
            self.set_calls = 0

        def set(self, value):
            self.set_calls += 1
            super().set(value)

    output = CountingOutput()
    audit = AuditLog(tmp_path / "api.jsonl")
    app = device_api.create_app(output=output, token="secret", audit=audit)
    headers = {"X-API-Token": "secret", "Idempotency-Key": "request-0001"}

    with TestClient(app) as client:
        first = client.put("/output", headers=headers, json={"value": 0.75})
        replay = client.put("/output", headers=headers, json={"value": 0.75})

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert output.set_calls == 1
    assert len(audit.read(kind="api_output_write")) == 1
    assert len(audit.read(kind="api_write_replayed")) == 1


def test_idempotency_key_rejects_different_command(tmp_path):
    app = device_api.create_app(
        token="secret",
        audit=AuditLog(tmp_path / "api.jsonl"),
    )
    headers = {"X-API-Token": "secret", "Idempotency-Key": "request-0002"}

    with TestClient(app) as client:
        assert client.put("/output", headers=headers, json={"value": 0.25}).status_code == 200
        conflict = client.put("/output", headers=headers, json={"value": 0.5})

    assert conflict.status_code == 409


def test_idempotency_survives_app_restart_when_audit_is_configured(tmp_path):
    audit = AuditLog(tmp_path / "api.jsonl")
    headers = {"X-API-Token": "secret", "Idempotency-Key": "request-0003"}
    first_output = SimulatedDigitalOutput()
    with TestClient(
        device_api.create_app(output=first_output, token="secret", audit=audit)
    ) as client:
        client.put("/output", headers=headers, json={"value": 0.4})

    replacement_output = SimulatedDigitalOutput()
    with TestClient(
        device_api.create_app(output=replacement_output, token="secret", audit=audit)
    ) as client:
        replay = client.put("/output", headers=headers, json={"value": 0.4})

    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replacement_output.value == 0.0
    assert replay.json() == {"value": 0.0}


def test_rejects_short_idempotency_key():
    with TestClient(device_api.create_app(token="secret")) as client:
        response = client.put(
            "/output",
            headers={"X-API-Token": "secret", "Idempotency-Key": "short"},
            json={"value": 0.5},
        )

    assert response.status_code == 422
