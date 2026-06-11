"""AIDOS MVP lifecycle orchestration service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from aidos.adapters import AnsibleAdapter, ApiAdapter, CliAdapter, McpAdapter, PlaywrightAdapter, PyatsAdapter
from aidos.execution import ApprovalStore, ExecutionTask, NcpExecutor
from aidos.ingestion import ingest_inputs
from aidos.logging_utils import get_logger, log_event
from aidos.netbox_sync import NetBoxClient, build_netbox_payload
from aidos.observed import parse_observed_state
from aidos.planning import (
    build_agentic_task_graph,
    build_ansible_bundle,
    build_ansible_playbook,
    build_runbook_plan,
)
from aidos.schemas import ChatAnswer, Evidence, EvidenceBundle, ExecutionRecord
from aidos.truth import build_canonical_sot
from aidos.validation import validate_sot

LOGGER = get_logger("aidos.orchestrator")


def set_task_approval(
    output_dir: str,
    task_id: str,
    status: str,
    reviewer: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Persist approval decision for a task."""
    store = ApprovalStore(Path(output_dir) / "state" / "approvals.json")
    record = store.set(task_id, status=status, reviewer=reviewer, reason=reason)
    return record.model_dump(mode="json")


def get_task_approval(output_dir: str, task_id: str) -> dict[str, Any]:
    """Read approval state for a task."""
    store = ApprovalStore(Path(output_dir) / "state" / "approvals.json")
    return store.get(task_id).model_dump(mode="json")


def list_task_approvals(output_dir: str) -> list[dict[str, Any]]:
    """List all known approval records."""
    store = ApprovalStore(Path(output_dir) / "state" / "approvals.json")
    return [entry.model_dump(mode="json") for entry in store.list()]


@dataclass(slots=True)
class WorkflowArtifacts:
    """Artifact paths emitted from the full MVP workflow."""

    canonical_sot_json: Path
    netbox_sync_payloads_json: Path
    validation_report_json: Path
    missing_data_report_json: Path
    runbook_yaml: Path
    ansible_playbook_yml: Path
    ansible_bundle_dir: Path
    agentic_task_graph_json: Path
    evidence_bundle_json: Path
    observed_state_snapshot_json: Path
    post_execution_verification_report_json: Path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_ansible_bundle(bundle_dir: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = bundle_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _collect_evidence(
    validation_report: dict[str, Any],
    execution_records: list[ExecutionRecord],
    intake_evidence: list[Evidence],
) -> EvidenceBundle:
    findings = validation_report.get("critical", []) + validation_report.get("warning", []) + validation_report.get("passed", [])
    validation_evidence = [
        Evidence.model_validate(item)
        for finding in findings
        for item in finding.get("evidence", [])
    ]

    execution_evidence = [
        entry
        for record in execution_records
        for entry in record.evidence
    ]

    deployment = validation_report.get("deployment", "aidos-deployment")
    return EvidenceBundle(
        deployment=deployment,
        evidence=[*intake_evidence, *validation_evidence, *execution_evidence],
        generated_at=datetime.now(timezone.utc),
    )


def run_mvp_workflow(
    *,
    survey_path: str,
    output_dir: str,
    bom_path: str | None = None,
    workload_path: str | None = None,
    pyats_testbed_path: str | None = None,
    context_path: str | None = None,
    network_layout_path: str | None = None,
    observed_path: str | None = None,
    sync_netbox: bool = False,
    execute: bool = False,
    auto_approve: bool = False,
    netbox_base_url: str | None = None,
    netbox_token: str | None = None,
    netbox_dry_run: bool | None = None,
) -> WorkflowArtifacts:
    """Run AIDOS intake-to-verify lifecycle and emit required artifacts."""

    log_event(
        LOGGER,
        "workflow.start",
        survey_path=survey_path,
        bom_path=bom_path,
        workload_path=workload_path,
        execute=execute,
        sync_netbox=sync_netbox,
    )

    bundle = ingest_inputs(
        survey_path,
        bom_path=bom_path,
        workload_path=workload_path,
        context_path=context_path,
        network_layout_path=network_layout_path,
    )
    sot = build_canonical_sot(bundle)

    validation_report, missing_data_report = validate_sot(sot, observed_path=observed_path)
    netbox_payload = build_netbox_payload(sot, network_layout=bundle.network_layout)

    sync_result: dict[str, Any] | None = None
    if sync_netbox:
        if netbox_base_url is None and netbox_token is None and netbox_dry_run is None:
            netbox_client = NetBoxClient.from_env()
        else:
            netbox_client = NetBoxClient(
                base_url=netbox_base_url or "http://netbox.local",
                token=netbox_token,
                dry_run=bool(netbox_dry_run),
            )
        sync_result = netbox_client.upsert_payload(netbox_payload)
        log_event(LOGGER, "netbox.sync", result=sync_result)

    runbook = build_runbook_plan(sot, validation_report, pyats_testbed_path=pyats_testbed_path)
    ansible_playbook = build_ansible_playbook(runbook)
    ansible_bundle = build_ansible_bundle(
        runbook,
        architecture={
            "project": sot.project.model_dump(mode="json"),
            "intent": sot.intent.model_dump(mode="json"),
            "expected": sot.expected.model_dump(mode="json"),
            "site": sot.site.model_dump(mode="json"),
            "workload": sot.workload.model_dump(mode="json") if sot.workload else None,
            "netbox_payload": netbox_payload.model_dump(mode="json"),
        },
    )
    task_graph = build_agentic_task_graph(runbook)

    execution_records: list[ExecutionRecord] = []
    if execute:
        log_event(LOGGER, "execution.start", task_count=len(runbook.tasks), auto_approve=auto_approve)
        approval_store = ApprovalStore(Path(output_dir) / "state" / "approvals.json")
        ncp = NcpExecutor(approval_store=approval_store)
        ncp.register_adapter("api", ApiAdapter())
        ncp.register_adapter("cli", CliAdapter())
        ncp.register_adapter("ansible", AnsibleAdapter())
        ncp.register_adapter("mcp", McpAdapter())
        ncp.register_adapter("playwright", PlaywrightAdapter())
        ncp.register_adapter("pyats", PyatsAdapter())

        for task in runbook.tasks:
            if task.approval_required and auto_approve:
                approval_store.set(task.id, "approved", reviewer="auto", reason="auto_approve enabled")
            elif task.approval_required:
                existing = approval_store.get(task.id)
                if existing.status not in {"approved", "rejected", "pending"}:
                    approval_store.set(task.id, "pending", reviewer=None, reason="Awaiting operator approval")

            ncp_task = ExecutionTask(
                task_id=task.id,
                adapter=task.preferred_executor,
                action=task.intent,
                payload=_build_execution_payload(task, pyats_testbed_path),
                fallback_adapters=task.fallback_executors,
                approval_required=task.approval_required,
            )
            result = ncp.run_task(ncp_task)
            status = result.status
            executor_used = str(result.output.get("adapter", task.preferred_executor))
            execution_records.append(
                ExecutionRecord(
                    task_id=task.id,
                    executor=executor_used,
                    status=status,
                    output=result.output,
                    evidence=result.evidence,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
            )
            log_event(
                LOGGER,
                "execution.record",
                task_id=task.id,
                executor=executor_used,
                status=status,
            )

        completed = sum(1 for record in execution_records if record.status == "completed")
        blocked_pending = sum(
            1 for record in execution_records if record.status == "blocked_pending_approval"
        )
        blocked_rejected = sum(
            1 for record in execution_records if record.status == "blocked_rejected"
        )
        failed = sum(1 for record in execution_records if record.status == "failed")
        log_event(
            LOGGER,
            "execution.summary",
            total=len(execution_records),
            completed=completed,
            blocked_pending_approval=blocked_pending,
            blocked_rejected=blocked_rejected,
            failed=failed,
        )

    if observed_path:
        observed_snapshot = parse_observed_state(observed_path).model_dump(mode="json")
    else:
        observed_snapshot = {
            "source": "execution.records",
            "signals": {
                "executed_tasks": [
                    {
                        "task_id": record.task_id,
                        "status": record.status,
                        "executor": record.executor,
                        "output": record.output,
                    }
                    for record in execution_records
                ]
            },
        }

    verification_report, _ = validate_sot(sot, observed_path=observed_path)

    evidence_bundle = _collect_evidence(
        validation_report.model_dump(mode="json"),
        execution_records,
        bundle.provenance,
    )

    out = Path(output_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = out / f"run_{stamp}"

    canonical_sot_path = run_dir / "canonical_sot.json"
    netbox_path = run_dir / "netbox_sync_payloads.json"
    validation_path = run_dir / "validation_report.json"
    missing_path = run_dir / "missing_data_report.json"
    runbook_path = run_dir / "runbook.yaml"
    ansible_path = run_dir / "ansible_playbook.yml"
    ansible_bundle_dir = run_dir / "ansible_bundle"
    graph_path = run_dir / "agentic_task_graph.json"
    evidence_path = run_dir / "evidence_bundle.json"
    observed_path_out = run_dir / "observed_state_snapshot.json"
    verify_path = run_dir / "post_execution_verification_report.json"

    _write_json(canonical_sot_path, sot.model_dump(mode="json"))
    _write_json(
        netbox_path,
        {
            "payload": netbox_payload.model_dump(mode="json"),
            "sync_result": sync_result,
        },
    )
    _write_json(validation_path, validation_report.model_dump(mode="json"))
    _write_json(missing_path, missing_data_report.model_dump(mode="json"))
    _write_yaml(runbook_path, runbook.model_dump(mode="python"))
    ansible_path.parent.mkdir(parents=True, exist_ok=True)
    ansible_path.write_text(ansible_playbook, encoding="utf-8")
    _write_ansible_bundle(ansible_bundle_dir, ansible_bundle)
    _write_json(graph_path, task_graph)
    _write_json(evidence_path, evidence_bundle.model_dump(mode="json"))
    _write_json(observed_path_out, observed_snapshot)
    _write_json(verify_path, verification_report.model_dump(mode="json"))

    latest = out / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for src in [
        canonical_sot_path,
        netbox_path,
        validation_path,
        missing_path,
        runbook_path,
        ansible_path,
        graph_path,
        evidence_path,
        observed_path_out,
        verify_path,
    ]:
        dst = latest / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    latest_bundle = latest / "ansible_bundle"
    _write_ansible_bundle(latest_bundle, ansible_bundle)

    log_event(
        LOGGER,
        "workflow.complete",
        run_dir=str(run_dir),
        artifacts=10,
        readiness=validation_report.readiness,
    )

    return WorkflowArtifacts(
        canonical_sot_json=canonical_sot_path,
        netbox_sync_payloads_json=netbox_path,
        validation_report_json=validation_path,
        missing_data_report_json=missing_path,
        runbook_yaml=runbook_path,
        ansible_playbook_yml=ansible_path,
        ansible_bundle_dir=ansible_bundle_dir,
        agentic_task_graph_json=graph_path,
        evidence_bundle_json=evidence_path,
        observed_state_snapshot_json=observed_path_out,
        post_execution_verification_report_json=verify_path,
    )


def _build_execution_payload(task: Any, pyats_testbed_path: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"target": task.target}
    if task.intent == "post_deploy_health_check":
        payload["commands"] = [
            "show version",
            "show ip interface brief",
            "show inventory",
        ]
        if pyats_testbed_path:
            payload["pyats_testbed_path"] = pyats_testbed_path
    return payload


def query_artifacts(output_dir: str, question: str) -> ChatAnswer:
    """Simple local retrieval over generated JSON/YAML artifacts."""
    root = Path(output_dir)
    latest = root / "latest"
    if not latest.exists():
        return ChatAnswer(
            message="No artifacts found yet. Run intake/validate/plan workflow first.",
            cited_artifacts=[],
            proposed_actions=["Run aidos flow with ingest and validate"],
        )

    terms = [token.lower() for token in question.split() if token.strip()]
    matches: list[tuple[str, str]] = []

    def _summarize_json_artifact(name: str, text: str) -> str:
        try:
            payload = json.loads(text)
        except Exception:
            return " ".join(text.split())[:260]

        if name == "canonical_sot.json" and isinstance(payload, dict):
            project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
            intent = payload.get("intent", {}) if isinstance(payload.get("intent"), dict) else {}
            site = payload.get("site", {}) if isinstance(payload.get("site"), dict) else {}
            bom_present = project.get("bom_present")
            site_name = project.get("site_name", "unknown")
            return (
                f"Project {project.get('project_name', 'unknown')} for {project.get('customer_name', 'unknown')} "
                f"at {site_name} with {intent.get('node_count', '?')} {intent.get('gpu_model', 'unknown')} nodes; "
                f"VLANs: {', '.join(str(v) for v in (site.get('vlan_ids') or intent.get('required_vlans') or [])) or 'none'}; "
                f"BOM present hint: {bom_present if bom_present is not None else 'unknown'}."
            )

        if name == "validation_report.json" and isinstance(payload, dict):
            return (
                f"Readiness {payload.get('readiness', 'unknown')}; "
                f"summary: {payload.get('summary', '').strip()[:180]}"
            )

        if name == "netbox_sync_payloads.json" and isinstance(payload, dict):
            sync = payload.get("sync_result", {}) if isinstance(payload.get("sync_result"), dict) else {}
            netbox = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
            return (
                f"NetBox sync {sync.get('status', 'unknown')} with "
                f"{len(netbox.get('sites', []))} sites, {len(netbox.get('racks', []))} racks, "
                f"{len(netbox.get('devices', []))} devices, {len(netbox.get('vlans', []))} VLANs, "
                f"{len(netbox.get('cables', []))} cables."
            )

        if name == "agentic_task_graph.json" and isinstance(payload, dict):
            nodes = payload.get("nodes", []) if isinstance(payload.get("nodes"), list) else []
            return f"Task graph for {payload.get('deployment', 'unknown')} with {len(nodes)} tasks."

        if name == "evidence_bundle.json" and isinstance(payload, dict):
            evidence = payload.get("evidence", []) if isinstance(payload.get("evidence"), list) else []
            return f"Evidence bundle for {payload.get('deployment', 'unknown')} with {len(evidence)} evidence items."

        return " ".join(text.split())[:260]

    for artifact in sorted(latest.iterdir()):
        if artifact.is_dir():
            continue
        raw_text = artifact.read_text(encoding="utf-8")
        text = raw_text.lower()
        score = sum(1 for term in terms if term in text)
        if score > 0:
            snippet = _summarize_json_artifact(artifact.name, raw_text)
            matches.append((artifact.name, snippet))

    if not matches:
        return ChatAnswer(
            message="No direct match found in current NeMoSys artifacts.",
            cited_artifacts=[p.name for p in latest.iterdir() if p.is_file()][:5],
            proposed_actions=["Try a narrower query using field names like readiness, vlan, or task_id"],
        )

    top = matches[:3]
    cited = [name for name, _ in top]
    summary = "\n\n".join([f"{name}:\n{snippet}" for name, snippet in top])
    return ChatAnswer(
        message=f"Grounded matches from NeMoSys artifacts:\n\n{summary}",
        cited_artifacts=cited,
        proposed_actions=["Inspect full artifact for details", "Generate follow-on runbook updates"],
        mode="grounded",
    )
