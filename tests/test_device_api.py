import importlib

from fastapi.testclient import TestClient

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
