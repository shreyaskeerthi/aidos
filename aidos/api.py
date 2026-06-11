"""FastAPI service layer for AIDOS lifecycle, query/chat, and approvals."""

from __future__ import annotations

import shutil
import json
from pathlib import Path
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from aidos.chat import converse, get_session
from aidos.parsers import parse_network_layout_workbook, read_key_value_file
from aidos.orchestrator import (
    get_task_approval,
    list_task_approvals,
    query_artifacts,
    run_mvp_workflow,
    set_task_approval,
)
from aidos.project_store import ProjectStore
from aidos.state_store import JsonStateStore
from aidos.ui_dashboard import (
    get_latest_summary,
    list_latest_artifacts,
    render_dashboard_html,
    render_operator_app_html,
)

app = FastAPI(title="AIDOS API", version="0.1.0")
PROJECTS = ProjectStore("aidos/outputs")


def _normalize_output_dir(path_value: str) -> str:
    """Normalize persisted output paths across Windows/Linux separators."""
    text = str(path_value or "").strip()
    if not text:
        return "aidos/outputs"
    return str(Path(text.replace("\\", "/")))


def _normalize_project_payload(project: dict) -> dict:
    normalized = dict(project)
    normalized["output_dir"] = _normalize_output_dir(str(normalized.get("output_dir", "")))
    return normalized


def _read_json_file(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_run_debug_summary(
    *,
    resolved_inputs: dict[str, str | None],
    netbox_sync_payloads_json: Path,
    validation_report_json: Path,
) -> dict:
    netbox_data = _read_json_file(netbox_sync_payloads_json)
    validation_data = _read_json_file(validation_report_json)

    payload = netbox_data.get("payload") if isinstance(netbox_data.get("payload"), dict) else {}
    sync_result = netbox_data.get("sync_result") if isinstance(netbox_data.get("sync_result"), dict) else {}
    reconciliation = sync_result.get("reconciliation") if isinstance(sync_result.get("reconciliation"), dict) else {}

    return {
        "resolved_inputs": resolved_inputs,
        "readiness": validation_data.get("readiness"),
        "netbox": {
            "payload_counts": {
                "sites": len(payload.get("sites", [])) if isinstance(payload.get("sites", []), list) else 0,
                "racks": len(payload.get("racks", [])) if isinstance(payload.get("racks", []), list) else 0,
                "devices": len(payload.get("devices", [])) if isinstance(payload.get("devices", []), list) else 0,
                "vlans": len(payload.get("vlans", [])) if isinstance(payload.get("vlans", []), list) else 0,
                "prefixes": len(payload.get("prefixes", [])) if isinstance(payload.get("prefixes", []), list) else 0,
                "cables": len(payload.get("cables", [])) if isinstance(payload.get("cables", []), list) else 0,
            },
            "sync_status": sync_result.get("status"),
            "base_url": sync_result.get("base_url"),
            "reconciliation_counts": {
                "sites": len(reconciliation.get("sites", [])) if isinstance(reconciliation.get("sites", []), list) else 0,
                "racks": len(reconciliation.get("racks", [])) if isinstance(reconciliation.get("racks", []), list) else 0,
                "devices": len(reconciliation.get("devices", [])) if isinstance(reconciliation.get("devices", []), list) else 0,
                "vlans": len(reconciliation.get("vlans", [])) if isinstance(reconciliation.get("vlans", []), list) else 0,
                "prefixes": len(reconciliation.get("prefixes", [])) if isinstance(reconciliation.get("prefixes", []), list) else 0,
                "cables": len(reconciliation.get("cables", [])) if isinstance(reconciliation.get("cables", []), list) else 0,
            },
            "error_count": len(sync_result.get("errors", [])) if isinstance(sync_result.get("errors", []), list) else 0,
        },
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "aidos-api",
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> dict[str, str]:
    return {"status": "no-favicon"}


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return render_operator_app_html()


@app.get("/ui/legacy", response_class=HTMLResponse)
def ui_legacy(output_dir: str = "aidos/outputs") -> str:
    summary = get_latest_summary(output_dir)
    return render_dashboard_html(summary)


@app.get("/v1/ui/summary")
def ui_summary(output_dir: str = "aidos/outputs") -> dict:
    return get_latest_summary(output_dir)


class FlowRequest(BaseModel):
    survey_path: str
    output_dir: str = "aidos/outputs"
    bom_path: str | None = None
    workload_path: str | None = None
    pyats_testbed_path: str | None = None
    context_path: str | None = None
    network_layout_path: str | None = None
    observed_path: str | None = None
    sync_netbox: bool = False
    execute: bool = False
    auto_approve: bool = False
    netbox_base_url: str | None = None
    netbox_token: str | None = None
    netbox_dry_run: bool = False


class QueryRequest(BaseModel):
    output_dir: str = "aidos/outputs"
    question: str


class ChatRequest(BaseModel):
    output_dir: str = "aidos/outputs"
    message: str
    session_id: str = "default"


class ApprovalRequest(BaseModel):
    status: str = Field(pattern="^(pending|approved|rejected)$")
    reviewer: str | None = None
    reason: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""


class ProjectFlowRequest(BaseModel):
    survey_path: str
    bom_path: str | None = None
    workload_path: str | None = None
    pyats_testbed_path: str | None = None
    context_path: str | None = None
    network_layout_path: str | None = None
    observed_path: str | None = None
    sync_netbox: bool = False
    execute: bool = False
    auto_approve: bool = False
    netbox_base_url: str | None = None
    netbox_token: str | None = None
    netbox_dry_run: bool = False


class ProjectChatRequest(BaseModel):
    message: str
    session_id: str = "ops-default"


class IntakeClearRequest(BaseModel):
    remove_uploaded_files: bool = True


class IntakeAnalysisRequest(BaseModel):
    survey_path: str | None = None
    bom_path: str | None = None
    workload_path: str | None = None
    context_path: str | None = None
    network_layout_path: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "aidos-api"}


@app.get("/v1/projects")
def list_projects() -> list[dict]:
    return [_normalize_project_payload(project) for project in PROJECTS.list_projects()]


@app.post("/v1/projects")
def create_project(payload: ProjectCreateRequest) -> dict:
    return _normalize_project_payload(PROJECTS.create_project(payload.name, payload.description))


@app.get("/v1/projects/{project_id}")
def get_project(project_id: str) -> dict:
    project = _require_project(project_id)
    PROJECTS.select_project(project_id)
    return project


def _require_project(project_id: str) -> dict:
    project = PROJECTS.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _normalize_project_payload(project)


@app.get("/v1/projects/{project_id}/summary")
def project_summary(project_id: str) -> dict:
    project = _require_project(project_id)
    return get_latest_summary(project["output_dir"])


@app.get("/v1/projects/{project_id}/artifacts")
def project_artifacts(project_id: str) -> list[dict]:
    project = _require_project(project_id)
    return list_latest_artifacts(project["output_dir"])


@app.get("/v1/projects/{project_id}/artifacts/{artifact_path:path}")
def project_artifact_download(project_id: str, artifact_path: str):
    project = _require_project(project_id)
    latest = Path(project["output_dir"]) / "latest"
    target = (latest / artifact_path).resolve()
    if not str(target).startswith(str(latest.resolve())):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(target), filename=target.name)


def _save_upload(base_dir: Path, upload: UploadFile | None, label: str) -> str | None:
    if upload is None or upload.filename is None:
        return None
    safe_name = "".join(ch for ch in upload.filename if ch.isalnum() or ch in {"-", "_", "."})
    if not safe_name:
        safe_name = f"{label}.dat"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = base_dir / f"{stamp}_{label}_{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = upload.file.read()
    target.write_bytes(content)
    return str(target)


def _load_latest_inputs(project_output_dir: str) -> dict[str, str | None]:
    intake_meta = Path(project_output_dir) / "state" / "latest_inputs.json"
    if not intake_meta.exists():
        return {
            "survey_path": None,
            "bom_path": None,
            "workload_path": None,
            "context_path": None,
            "network_layout_path": None,
        }
    try:
        payload = JsonStateStore(intake_meta).read()
    except Exception:
        payload = {}
    return {
        "survey_path": payload.get("survey_path"),
        "bom_path": payload.get("bom_path"),
        "workload_path": payload.get("workload_path"),
        "context_path": payload.get("context_path"),
        "network_layout_path": payload.get("network_layout_path"),
    }


def _classify_intake_path(path: str) -> str | None:
    try:
        normalized = read_key_value_file(path)
    except Exception:
        return None

    keys = set(normalized.keys())
    if "gpu_model" in keys:
        return "bom"

    workload_markers = {
        "workload_name",
        "gpu_model_preference",
        "desired_node_count",
        "latency_target_ms",
        "throughput_target_tps",
        "storage_tib",
        "network_profile",
    }
    if keys.intersection(workload_markers):
        return "workload"

    survey_markers = {
        "loading_dock",
        "server_lift",
        "rack_floor_psf",
        "liquid_cooling",
        "power_profile",
        "available_circuits",
        "uplinks",
        "ports_40g",
        "vlan_config_needed",
        "vlan_ids",
        "network_diagram_provided",
        "layout_blueprint_provided",
        "available_rack_slots",
        "available_power_kw",
        "available_cooling_kw",
    }
    if keys.intersection(survey_markers):
        return "survey"

    context_markers = {"customer_name", "project_name", "region", "site_name"}
    if keys.intersection(context_markers):
        return "context"

    return None


def _reclassify_uploaded_inputs(paths: dict[str, str | None]) -> tuple[dict[str, str | None], dict[str, str]]:
    corrected: dict[str, str | None] = {
        "survey_path": paths.get("survey_path"),
        "bom_path": paths.get("bom_path"),
        "workload_path": paths.get("workload_path"),
        "context_path": paths.get("context_path"),
    }
    remapped: dict[str, str] = {}
    detected_by_label: dict[str, list[tuple[str, str]]] = {}

    for key, path in paths.items():
        if not path:
            continue
        detected = _classify_intake_path(path)
        if detected is not None:
            detected_by_label.setdefault(detected, []).append((key, path))

    # Only use semantic reassignment to fill missing slots; do not override explicit upload fields.
    for detected_label in ["survey", "bom", "workload", "context"]:
        target_key = f"{detected_label}_path"
        if corrected.get(target_key):
            continue

        candidates = detected_by_label.get(detected_label) or []
        if not candidates:
            continue

        source = None
        for src_key, src_path in candidates:
            if src_key == target_key:
                source = (src_key, src_path)
                break
        if source is None:
            source = candidates[0]

        src_key, src_path = source
        corrected[target_key] = src_path
        if src_key != target_key:
            remapped[src_key] = target_key

    # Fill any missing targets with original uploads that were not semantically mapped.
    for key, path in paths.items():
        if not path:
            continue
        if key in remapped:
            continue
        if corrected.get(key) is None:
            corrected[key] = path

    return corrected, remapped


def _detect_network_layout_path(paths: dict[str, str | None]) -> str | None:
    """Return the first uploaded Excel file that parses as a network layout workbook."""
    for key in ["survey_path", "bom_path", "workload_path", "context_path"]:
        candidate = paths.get(key)
        if not candidate:
            continue
        suffix = Path(candidate).suffix.lower()
        if suffix not in {".xlsx", ".xlsm", ".xls"}:
            continue
        try:
            parsed = parse_network_layout_workbook(candidate)
        except Exception:
            continue
        if parsed.get("vlans") or parsed.get("cables"):
            return candidate
    return None


@app.post("/v1/projects/{project_id}/intake/upload")
def project_upload_inputs(
    project_id: str,
    survey: UploadFile | None = File(default=None),
    bom: UploadFile | None = File(default=None),
    workload: UploadFile | None = File(default=None),
    context: UploadFile | None = File(default=None),
    replace_existing: bool = True,
) -> dict:
    project = _require_project(project_id)
    intake_dir = Path(project["output_dir"]) / "intake"

    paths = {
        "survey_path": _save_upload(intake_dir, survey, "survey"),
        "bom_path": _save_upload(intake_dir, bom, "bom"),
        "workload_path": _save_upload(intake_dir, workload, "workload"),
        "context_path": _save_upload(intake_dir, context, "context"),
    }
    corrected_paths, remapped = _reclassify_uploaded_inputs(paths)
    detected_network_layout_path = _detect_network_layout_path(corrected_paths)

    state_path = Path(project["output_dir"]) / "state" / "latest_inputs.json"
    latest = JsonStateStore(state_path).read()
    if replace_existing:
        latest.update(
            {
                "survey_path": None,
                "bom_path": None,
                "workload_path": None,
                "context_path": None,
                "network_layout_path": None,
            }
        )
    for key, value in corrected_paths.items():
        if value:
            latest[key] = value
    if detected_network_layout_path:
        latest["network_layout_path"] = detected_network_layout_path
    JsonStateStore(state_path).write(latest)

    return {
        "project_id": project_id,
        "saved": latest,
        "remapped": remapped,
        "replace_existing": replace_existing,
        "detected_network_layout_path": detected_network_layout_path,
    }


@app.post("/v1/projects/{project_id}/intake/clear")
def project_clear_inputs(project_id: str, payload: IntakeClearRequest | None = None) -> dict:
    project = _require_project(project_id)
    remove_uploaded_files = True if payload is None else bool(payload.remove_uploaded_files)

    state_path = Path(project["output_dir"]) / "state" / "latest_inputs.json"
    cleared = {
        "survey_path": None,
        "bom_path": None,
        "workload_path": None,
        "context_path": None,
        "network_layout_path": None,
    }
    JsonStateStore(state_path).write(cleared)

    removed_files = 0
    intake_dir = Path(project["output_dir"]) / "intake"
    if remove_uploaded_files and intake_dir.exists() and intake_dir.is_dir():
        for item in intake_dir.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
                removed_files += 1
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)

    return {
        "project_id": project_id,
        "cleared": cleared,
        "remove_uploaded_files": remove_uploaded_files,
        "removed_files": removed_files,
    }


@app.post("/v1/projects/{project_id}/flow")
def project_flow(project_id: str, payload: ProjectFlowRequest) -> dict:
    project = _require_project(project_id)
    latest = _load_latest_inputs(project["output_dir"])

    survey_path = payload.survey_path or latest.get("survey_path")
    bom_path = payload.bom_path or latest.get("bom_path")
    workload_path = payload.workload_path or latest.get("workload_path")
    context_path = payload.context_path or latest.get("context_path")
    network_layout_path = payload.network_layout_path or latest.get("network_layout_path")

    if not network_layout_path and survey_path:
        suffix = Path(survey_path).suffix.lower()
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            try:
                parsed = parse_network_layout_workbook(survey_path)
            except Exception:
                parsed = {"vlans": [], "cables": []}
            if parsed.get("vlans") or parsed.get("cables"):
                network_layout_path = survey_path

    if not survey_path:
        raise HTTPException(
            status_code=400,
            detail="survey_path is required. Provide it in form or upload survey first.",
        )
    try:
        artifacts = run_mvp_workflow(
            survey_path=survey_path,
            output_dir=project["output_dir"],
            bom_path=bom_path,
            workload_path=workload_path,
            pyats_testbed_path=payload.pyats_testbed_path,
            context_path=context_path,
            network_layout_path=network_layout_path,
            observed_path=payload.observed_path,
            sync_netbox=payload.sync_netbox,
            execute=payload.execute,
            auto_approve=payload.auto_approve,
            netbox_base_url=payload.netbox_base_url,
            netbox_token=payload.netbox_token,
            netbox_dry_run=payload.netbox_dry_run,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Intake file validation failed. Check survey/BOM/workload file mapping and required fields.",
                "errors": exc.errors(),
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Flow execution failed due to unexpected input or parsing error.",
                "error": str(exc),
                "hint": "Verify uploaded survey/BOM/workbook formats and field mappings.",
            },
        ) from exc

    run_debug = _build_run_debug_summary(
        resolved_inputs={
            "survey_path": survey_path,
            "bom_path": bom_path,
            "workload_path": workload_path,
            "context_path": context_path,
            "network_layout_path": network_layout_path,
            "observed_path": payload.observed_path,
        },
        netbox_sync_payloads_json=artifacts.netbox_sync_payloads_json,
        validation_report_json=artifacts.validation_report_json,
    )

    return {
        "project_id": project_id,
        "canonical_sot_json": str(artifacts.canonical_sot_json),
        "netbox_sync_payloads_json": str(artifacts.netbox_sync_payloads_json),
        "validation_report_json": str(artifacts.validation_report_json),
        "missing_data_report_json": str(artifacts.missing_data_report_json),
        "runbook_yaml": str(artifacts.runbook_yaml),
        "ansible_playbook_yml": str(artifacts.ansible_playbook_yml),
        "ansible_bundle_dir": str(artifacts.ansible_bundle_dir),
        "agentic_task_graph_json": str(artifacts.agentic_task_graph_json),
        "evidence_bundle_json": str(artifacts.evidence_bundle_json),
        "observed_state_snapshot_json": str(artifacts.observed_state_snapshot_json),
        "post_execution_verification_report_json": str(artifacts.post_execution_verification_report_json),
        "run_debug": run_debug,
    }


@app.post("/v1/projects/{project_id}/intake/analyze")
def project_analyze_intake(project_id: str, payload: IntakeAnalysisRequest) -> dict:
    project = _require_project(project_id)
    latest = _load_latest_inputs(project["output_dir"])

    survey_path = payload.survey_path or latest.get("survey_path")
    bom_path = payload.bom_path or latest.get("bom_path")
    workload_path = payload.workload_path or latest.get("workload_path")
    context_path = payload.context_path or latest.get("context_path")
    network_layout_path = payload.network_layout_path or latest.get("network_layout_path")

    if not survey_path:
        raise HTTPException(status_code=400, detail="survey_path is required for intake analysis")

    inferred_layout = network_layout_path
    if not inferred_layout and survey_path:
        suffix = Path(survey_path).suffix.lower()
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            try:
                parsed = parse_network_layout_workbook(survey_path)
            except Exception:
                parsed = {"vlans": [], "cables": []}
            if parsed.get("vlans") or parsed.get("cables"):
                inferred_layout = survey_path

    artifacts = run_mvp_workflow(
        survey_path=survey_path,
        output_dir=project["output_dir"],
        bom_path=bom_path,
        workload_path=workload_path,
        context_path=context_path,
        network_layout_path=inferred_layout,
        observed_path=None,
        sync_netbox=False,
        execute=False,
        auto_approve=False,
    )

    debug = _build_run_debug_summary(
        resolved_inputs={
            "survey_path": survey_path,
            "bom_path": bom_path,
            "workload_path": workload_path,
            "context_path": context_path,
            "network_layout_path": inferred_layout,
            "observed_path": None,
        },
        netbox_sync_payloads_json=artifacts.netbox_sync_payloads_json,
        validation_report_json=artifacts.validation_report_json,
    )

    answer = converse(
        (
            "Analyze this intake extraction result for completeness and likely misses. "
            f"Resolved inputs: {debug.get('resolved_inputs')} | "
            f"NetBox payload counts: {debug.get('netbox', {}).get('payload_counts')}"
        ),
        project["output_dir"],
        session_id="intake-analysis",
    )

    return {
        "project_id": project_id,
        "run_debug": debug,
        "analysis": answer.model_dump(mode="json"),
        "artifacts": {
            "canonical_sot_json": str(artifacts.canonical_sot_json),
            "netbox_sync_payloads_json": str(artifacts.netbox_sync_payloads_json),
            "validation_report_json": str(artifacts.validation_report_json),
            "missing_data_report_json": str(artifacts.missing_data_report_json),
        },
    }


@app.post("/v1/projects/{project_id}/chat")
def project_chat(project_id: str, payload: ProjectChatRequest) -> dict:
    project = _require_project(project_id)
    answer = converse(payload.message, project["output_dir"], session_id=payload.session_id)
    return answer.model_dump(mode="json")


@app.get("/v1/projects/{project_id}/chat/sessions/{session_id}")
def project_chat_session(project_id: str, session_id: str) -> dict:
    project = _require_project(project_id)
    return get_session(session_id, project["output_dir"])


@app.post("/v1/flow")
def flow(payload: FlowRequest) -> dict:
    try:
        artifacts = run_mvp_workflow(
            survey_path=payload.survey_path,
            output_dir=payload.output_dir,
            bom_path=payload.bom_path,
            workload_path=payload.workload_path,
            pyats_testbed_path=payload.pyats_testbed_path,
            context_path=payload.context_path,
            network_layout_path=payload.network_layout_path,
            observed_path=payload.observed_path,
            sync_netbox=payload.sync_netbox,
            execute=payload.execute,
            auto_approve=payload.auto_approve,
            netbox_base_url=payload.netbox_base_url,
            netbox_token=payload.netbox_token,
            netbox_dry_run=payload.netbox_dry_run,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Intake file validation failed. Check survey/BOM/workload file mapping and required fields.",
                "errors": exc.errors(),
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Flow execution failed due to unexpected input or parsing error.",
                "error": str(exc),
                "hint": "Verify uploaded survey/BOM/workbook formats and field mappings.",
            },
        ) from exc

    run_debug = _build_run_debug_summary(
        resolved_inputs={
            "survey_path": payload.survey_path,
            "bom_path": payload.bom_path,
            "workload_path": payload.workload_path,
            "context_path": payload.context_path,
            "network_layout_path": payload.network_layout_path,
            "observed_path": payload.observed_path,
        },
        netbox_sync_payloads_json=artifacts.netbox_sync_payloads_json,
        validation_report_json=artifacts.validation_report_json,
    )

    return {
        "canonical_sot_json": str(artifacts.canonical_sot_json),
        "netbox_sync_payloads_json": str(artifacts.netbox_sync_payloads_json),
        "validation_report_json": str(artifacts.validation_report_json),
        "missing_data_report_json": str(artifacts.missing_data_report_json),
        "runbook_yaml": str(artifacts.runbook_yaml),
        "ansible_playbook_yml": str(artifacts.ansible_playbook_yml),
        "ansible_bundle_dir": str(artifacts.ansible_bundle_dir),
        "agentic_task_graph_json": str(artifacts.agentic_task_graph_json),
        "evidence_bundle_json": str(artifacts.evidence_bundle_json),
        "observed_state_snapshot_json": str(artifacts.observed_state_snapshot_json),
        "post_execution_verification_report_json": str(artifacts.post_execution_verification_report_json),
        "run_debug": run_debug,
    }


@app.post("/v1/query")
def query(payload: QueryRequest) -> dict:
    answer = query_artifacts(payload.output_dir, payload.question)
    return answer.model_dump(mode="json")


@app.post("/v1/chat")
def chat(payload: ChatRequest) -> dict:
    answer = converse(payload.message, payload.output_dir, session_id=payload.session_id)
    return answer.model_dump(mode="json")


@app.get("/v1/chat/sessions/{session_id}")
def session(session_id: str, output_dir: str = "aidos/outputs") -> dict:
    return get_session(session_id, output_dir)


@app.post("/v1/approvals/{task_id}")
def approval_set(task_id: str, payload: ApprovalRequest, output_dir: str = "aidos/outputs") -> dict:
    return set_task_approval(
        output_dir=output_dir,
        task_id=task_id,
        status=payload.status,
        reviewer=payload.reviewer,
        reason=payload.reason,
    )


@app.get("/v1/approvals/{task_id}")
def approval_get(task_id: str, output_dir: str = "aidos/outputs") -> dict:
    return get_task_approval(output_dir, task_id)


@app.get("/v1/approvals")
def approvals(output_dir: str = "aidos/outputs") -> list[dict]:
    return list_task_approvals(output_dir)
