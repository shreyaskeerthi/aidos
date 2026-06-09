from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import aidos.api as api_module
from aidos.project_store import ProjectStore


def test_project_library_and_artifact_download(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "PROJECTS", ProjectStore(str(tmp_path / "outputs")))
    client = TestClient(api_module.app)

    created = client.post(
        "/v1/projects",
        json={"name": "Lab One", "description": "Primary project"},
    )
    assert created.status_code == 200
    project = created.json()

    out = Path(project["output_dir"])
    latest = out / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "validation_report.json").write_text(
        json.dumps({"deployment": "lab", "readiness": "ready"}),
        encoding="utf-8",
    )

    listed = client.get("/v1/projects")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    artifacts = client.get(f"/v1/projects/{project['id']}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()

    dl = client.get(
        f"/v1/projects/{project['id']}/artifacts/validation_report.json"
    )
    assert dl.status_code == 200
    assert "ready" in dl.text


def test_ui_route_returns_interactive_console() -> None:
    client = TestClient(api_module.app)
    response = client.get("/ui")
    assert response.status_code == 200
    assert "AIDOS Operator Console" in response.text
    assert "AIDOS Projects" in response.text
