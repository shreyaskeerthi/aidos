from __future__ import annotations

import json
from pathlib import Path

from aidos.chat import converse, get_session
from aidos.execution import ApprovalStore
from aidos.netbox_sync import NetBoxClient
from aidos.orchestrator import run_mvp_workflow
from aidos.schemas import NetBoxPayload


def test_approval_store_persists_records(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "state" / "approvals.json")

    pending = store.get("task-001")
    assert pending.status == "pending"

    approved = store.set("task-001", "approved", reviewer="ops", reason="validated")
    assert approved.status == "approved"

    loaded = store.get("task-001")
    assert loaded.status == "approved"
    assert loaded.reviewer == "ops"


def test_chat_session_is_persistent(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    latest = out / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "validation_report.json").write_text(
        json.dumps({"readiness": "ready", "summary": "ok"}),
        encoding="utf-8",
    )

    answer = converse("what is missing", str(out), session_id="ops-session")
    assert answer.message

    session = get_session("ops-session", str(out))
    assert session.get("session_id") == "ops-session"
    assert len(session.get("turns", [])) >= 2


def test_netbox_client_dry_run_reconciliation() -> None:
    client = NetBoxClient(base_url="http://netbox.local", token=None, dry_run=True)
    payload = NetBoxPayload(
        sites=[{"name": "site-a", "slug": "site-a"}],
        racks=[{"name": "rack-a", "site": "site-a"}],
        devices=[{"name": "node-1", "site": "site-a"}],
        vlans=[{"name": "vlan-101", "vid": 101}],
        prefixes=[{"prefix": "10.1.0.0/24"}],
    )

    result = client.upsert_payload(payload)
    assert result["status"] == "dry_run"
    assert len(result["reconciliation"]["devices"]) == 1


def test_execute_flow_respects_pending_approvals(tmp_path: Path) -> None:
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
        "deployment_name": "aidos-approval",
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
        auto_approve=False,
    )

    observed = json.loads(artifacts.observed_state_snapshot_json.read_text(encoding="utf-8"))
    statuses = [entry["status"] for entry in observed["signals"]["executed_tasks"]]
    assert "blocked_pending_approval" in statuses
