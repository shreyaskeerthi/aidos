from __future__ import annotations

import json
from pathlib import Path

from aidos.chat import converse
from aidos.orchestrator import query_artifacts, run_mvp_workflow


def test_run_mvp_flow_emits_required_artifacts(tmp_path: Path) -> None:
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
        "deployment_name": "aidos-e2e",
        "gpu_model": "H100",
        "node_count": 8,
        "target_platform": "Cisco AI Pod",
    }

    survey_path = tmp_path / "survey.json"
    bom_path = tmp_path / "bom.json"
    survey_path.write_text(json.dumps(survey), encoding="utf-8")
    bom_path.write_text(json.dumps(bom), encoding="utf-8")

    artifacts = run_mvp_workflow(
        survey_path=str(survey_path),
        bom_path=str(bom_path),
        output_dir=str(tmp_path / "outputs"),
        execute=True,
        auto_approve=True,
    )

    assert artifacts.canonical_sot_json.exists()
    assert artifacts.netbox_sync_payloads_json.exists()
    assert artifacts.validation_report_json.exists()
    assert artifacts.missing_data_report_json.exists()
    assert artifacts.runbook_yaml.exists()
    assert artifacts.ansible_playbook_yml.exists()
    assert artifacts.agentic_task_graph_json.exists()
    assert artifacts.evidence_bundle_json.exists()
    assert artifacts.observed_state_snapshot_json.exists()
    assert artifacts.post_execution_verification_report_json.exists()


def test_query_and_chat_are_grounded(tmp_path: Path) -> None:
    out_dir = tmp_path / "outputs"
    latest = out_dir / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "validation_report.json").write_text(
        json.dumps({"readiness": "ready_with_warnings", "summary": "ok"}),
        encoding="utf-8",
    )

    answer = query_artifacts(str(out_dir), "readiness")
    assert "Grounded matches" in answer.message
    assert answer.cited_artifacts

    chat_answer = converse("what is missing", str(out_dir))
    assert chat_answer.message
