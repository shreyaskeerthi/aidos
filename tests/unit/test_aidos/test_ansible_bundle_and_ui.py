from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aidos.api import app
from aidos.orchestrator import run_mvp_workflow


def test_ansible_bundle_is_generated(tmp_path: Path) -> None:
    survey = {
        "loading_dock": "yes",
        "server_lift": "yes",
        "rack_floor_psf": 180,
        "available_circuits": "yes",
        "available_rack_slots": 4,
        "available_power_kw": 120,
        "available_cooling_kw": 100,
        "vlan_config_needed": "yes",
        "vlan_ids": ["101", "102"],
        "uplinks": "2x100G",
        "liquid_cooling": "yes",
        "network_diagram_provided": "yes",
        "layout_blueprint_provided": "yes",
    }
    bom = {
        "deployment_name": "aidos-bundle",
        "gpu_model": "H100",
        "node_count": 6,
    }

    survey_path = tmp_path / "survey.json"
    bom_path = tmp_path / "bom.json"
    survey_path.write_text(json.dumps(survey), encoding="utf-8")
    bom_path.write_text(json.dumps(bom), encoding="utf-8")

    artifacts = run_mvp_workflow(
        survey_path=str(survey_path),
        bom_path=str(bom_path),
        output_dir=str(tmp_path / "outputs"),
        execute=False,
    )

    assert (artifacts.ansible_bundle_dir / "README.md").exists()
    assert (artifacts.ansible_bundle_dir / "inventory" / "hosts.yml").exists()
    assert (artifacts.ansible_bundle_dir / "group_vars" / "all.yml.template").exists()
    assert (artifacts.ansible_bundle_dir / "playbooks" / "site.yml").exists()


def test_ui_endpoints_render() -> None:
    client = TestClient(app)
    response_summary = client.get("/v1/ui/summary")
    assert response_summary.status_code == 200
    assert "readiness" in response_summary.json()

    response_ui = client.get("/ui")
    assert response_ui.status_code == 200
    assert "AIDOS Operator Console" in response_ui.text

    response_legacy = client.get("/ui/legacy")
    assert response_legacy.status_code == 200
    assert "AIDOS Operator Dashboard" in response_legacy.text
