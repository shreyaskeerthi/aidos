from __future__ import annotations

import json
from pathlib import Path

from aidos.service import validate_deployment


def test_validate_deployment_pipeline_with_observed(tmp_path: Path) -> None:
    survey = {
        "loading_dock": "yes",
        "server_lift": "yes",
        "rack_floor_psf": 160,
        "liquid_cooling": "yes",
        "available_circuits": "yes",
        "power_profile": "208V 30A 3-phase",
        "vlan_config_needed": "yes",
        "vlan_ids": ["101", "102"],
        "network_diagram_provided": "yes",
        "layout_blueprint_provided": "yes",
        "available_rack_slots": 4,
        "available_power_kw": 120,
        "available_cooling_kw": 95,
        "uplinks": "2x100G",
        "ports_40g": "yes",
    }
    bom = {
        "deployment_name": "aidos-poc",
        "gpu_model": "H100",
        "node_count": 8,
        "target_platform": "Cisco AI Pod",
    }
    observed = {
        "gpu_model": "H100",
        "node_count": 8,
        "uplinks": "2x100G",
        "vlan_ids": "101,102",
        "liquid_cooling": "yes",
    }

    survey_path = tmp_path / "survey.json"
    bom_path = tmp_path / "bom.json"
    observed_path = tmp_path / "observed.json"
    survey_path.write_text(json.dumps(survey), encoding="utf-8")
    bom_path.write_text(json.dumps(bom), encoding="utf-8")
    observed_path.write_text(json.dumps(observed), encoding="utf-8")

    output = validate_deployment(str(survey_path), str(bom_path), str(observed_path))

    assert output.report.deployment == "aidos-poc"
    assert output.report.readiness in {"ready", "ready_with_warnings", "not_ready"}
    assert output.report.summary.startswith("Validation complete")
    assert output.normalized_survey["loading_dock"] is True
