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


def test_project_intake_clear_resets_saved_paths_and_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(api_module, "PROJECTS", ProjectStore(str(tmp_path / "outputs")))
    client = TestClient(api_module.app)

    created = client.post(
        "/v1/projects",
        json={"name": "Clear Intake Project", "description": "Clear test"},
    )
    assert created.status_code == 200
    project = created.json()

    output_dir = Path(project["output_dir"])
    intake_dir = output_dir / "intake"
    state_dir = output_dir / "state"
    intake_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    (intake_dir / "example-survey.json").write_text("{}", encoding="utf-8")
    (state_dir / "latest_inputs.json").write_text(
        json.dumps(
            {
                "survey_path": str(intake_dir / "example-survey.json"),
                "bom_path": "old-bom.json",
                "workload_path": "old-workload.yaml",
                "context_path": "old-context.json",
                "network_layout_path": "old-layout.xlsx",
            }
        ),
        encoding="utf-8",
    )

    cleared = client.post(
        f"/v1/projects/{project['id']}/intake/clear",
        json={"remove_uploaded_files": True},
    )
    assert cleared.status_code == 200
    payload = cleared.json()
    assert payload["removed_files"] >= 1
    assert payload["cleared"]["survey_path"] is None
    assert payload["cleared"]["bom_path"] is None
    assert payload["cleared"]["workload_path"] is None
    assert payload["cleared"]["context_path"] is None
    assert payload["cleared"]["network_layout_path"] is None

    latest = json.loads((state_dir / "latest_inputs.json").read_text(encoding="utf-8"))
    assert latest["survey_path"] is None
    assert latest["bom_path"] is None
    assert latest["workload_path"] is None
    assert latest["context_path"] is None
    assert latest["network_layout_path"] is None
    assert list(intake_dir.iterdir()) == []
