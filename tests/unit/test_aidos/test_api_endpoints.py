from __future__ import annotations

from fastapi.testclient import TestClient

from aidos.api import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_flow_endpoint_rejects_missing_bom_or_workload() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/flow",
        json={
            "survey_path": "missing.json",
            "output_dir": "aidos/outputs",
        },
    )
    assert response.status_code == 400
