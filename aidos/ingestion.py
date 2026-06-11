"""Ingestion and BOM-builder workflows for AIDOS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aidos.parsers import (
    parse_deployment_intent_workbook,
    parse_network_layout_workbook,
    parse_workbook_metadata,
    read_key_value_file,
)
from aidos.schemas import (
    DeploymentIntent,
    Evidence,
    ProjectContext,
    SiteSurvey,
    WorkloadProfile,
)


@dataclass(slots=True)
class IntakeBundle:
    """Parsed raw + normalized intake payloads."""

    project: ProjectContext
    survey: SiteSurvey
    intent: DeploymentIntent
    workload: WorkloadProfile | None
    network_layout: dict[str, list[dict[str, Any]]] | None
    normalized_inputs: dict[str, dict[str, Any]]
    provenance: list[Evidence]


def _ev(source: str, raw_value: Any, parser: str) -> Evidence:
    return Evidence(
        source=source,
        raw_value=raw_value,
        source_type="file",
        source_system="intake",
        parser_or_adapter=parser,
        timestamp=datetime.now(timezone.utc),
    )


def build_bom_from_workload(workload: WorkloadProfile) -> DeploymentIntent:
    """Generate deterministic BOM draft from workload requirements."""
    gpu_model = workload.gpu_model_preference.upper().strip()
    node_count = max(workload.desired_node_count, 1)
    target_platform = "Cisco AI Pod" if node_count >= 4 else "Compact AI Cluster"

    return DeploymentIntent(
        deployment_name=f"{workload.workload_name}-deployment",
        gpu_model=gpu_model,
        node_count=node_count,
        target_platform=target_platform,
        required_vlans=["101", "102"] if node_count >= 4 else ["101"],
    )


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return max(int(float(str(value).strip())), 1)
    except (TypeError, ValueError):
        return default


def _coerce_vlans(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def infer_intent_from_inputs(
    survey_raw: dict[str, Any],
    context_raw: dict[str, Any],
    network_layout: dict[str, list[dict[str, Any]]] | None,
) -> DeploymentIntent:
    """Infer deployment intent when no BOM/workload file is supplied.

    This keeps no-BOM intake adaptive for mixed workbook scenarios.
    """

    deployment_name = (
        str(
            survey_raw.get("deployment_name")
            or context_raw.get("project_name")
            or "aidos-adaptive-deployment"
        )
        .strip()
        .replace(" ", "-")
        .lower()
    )
    gpu_model = str(
        survey_raw.get("gpu_model")
        or context_raw.get("gpu_model")
        or context_raw.get("gpu_model_hint")
        or context_raw.get("gpu_model_preference")
        or "UNSPECIFIED"
    ).strip()
    node_count = _coerce_int(
        survey_raw.get("node_count")
        or context_raw.get("node_count")
        or context_raw.get("node_count_hint")
        or context_raw.get("desired_node_count"),
        default=4,
    )
    target_platform = str(
        survey_raw.get("target_platform")
        or context_raw.get("target_platform")
        or ("Cisco AI Pod" if node_count >= 4 else "Compact AI Cluster")
    ).strip()

    required_vlans = _coerce_vlans(
        survey_raw.get("required_vlans")
        or survey_raw.get("vlan_ids")
        or context_raw.get("required_vlans")
    )
    if not required_vlans and network_layout is not None:
        inferred = [str(item.get("vid")) for item in network_layout.get("vlans", []) if item.get("vid") is not None]
        required_vlans = sorted(set(inferred), key=lambda value: int(value) if value.isdigit() else value)

    return DeploymentIntent(
        deployment_name=deployment_name or "aidos-adaptive-deployment",
        gpu_model=gpu_model or "UNSPECIFIED",
        node_count=node_count,
        target_platform=target_platform or None,
        required_vlans=required_vlans,
    )


def _load_bom_payload(path_str: str) -> dict[str, Any]:
    suffix = Path(path_str).suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        try:
            return parse_deployment_intent_workbook(path_str)
        except Exception:
            # Fall back to generic key/value parser for non-BOM spreadsheets.
            return read_key_value_file(path_str)
    return read_key_value_file(path_str)


def _infer_intent_from_workbooks(*paths: str | None) -> DeploymentIntent | None:
    for path in paths:
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if suffix not in {".xlsx", ".xlsm", ".xls"}:
            continue
        try:
            payload = parse_deployment_intent_workbook(path)
            return DeploymentIntent.model_validate(payload)
        except Exception:
            continue
    return None


def ingest_inputs(
    survey_path: str,
    *,
    bom_path: str | None = None,
    workload_path: str | None = None,
    context_path: str | None = None,
    network_layout_path: str | None = None,
) -> IntakeBundle:
    """Ingest intake artifacts supporting BOM and no-BOM starting conditions."""

    survey_raw = read_key_value_file(survey_path)
    survey = SiteSurvey.model_validate(survey_raw)

    context_raw = read_key_value_file(context_path) if context_path else {}
    if not context_raw:
        survey_suffix = Path(survey_path).suffix.lower()
        if survey_suffix in {".xlsx", ".xlsm", ".xls"}:
            try:
                workbook_meta = parse_workbook_metadata(survey_path)
            except Exception:
                workbook_meta = {}
            context_raw = {
                "customer_name": workbook_meta.get("customer_name"),
                "project_name": workbook_meta.get("project_name"),
                "site_name": workbook_meta.get("site_name"),
                "node_count_hint": workbook_meta.get("node_count_hint"),
                "gpu_model_hint": workbook_meta.get("gpu_model_hint"),
                "bom_present": workbook_meta.get("bom_present"),
            }
            context_raw = {k: v for k, v in context_raw.items() if v is not None}
    network_layout = (
        parse_network_layout_workbook(network_layout_path)
        if network_layout_path
        else None
    )

    workload: WorkloadProfile | None = None
    workload_raw: dict[str, Any] | None = None
    invalid_bom_raw: dict[str, Any] | None = None
    if workload_path:
        workload_raw = read_key_value_file(workload_path)
        workload = WorkloadProfile.model_validate(workload_raw)

    if bom_path:
        bom_raw = _load_bom_payload(bom_path)
        try:
            intent = DeploymentIntent.model_validate(bom_raw)
            bom_mode = "provided_bom"
        except ValidationError:
            invalid_bom_raw = bom_raw
            workbook_intent = _infer_intent_from_workbooks(
                survey_path,
                context_path,
                network_layout_path,
            )
            if workbook_intent is not None:
                intent = workbook_intent
                bom_mode = "provided_bom_invalid_fallback_inferred_from_workbook_bom"
            else:
                intent = infer_intent_from_inputs(survey_raw, context_raw, network_layout)
                bom_mode = "provided_bom_invalid_fallback_inferred_from_inputs"
            bom_raw = intent.model_dump(mode="python")
    elif workload is not None:
        bom_raw = build_bom_from_workload(workload).model_dump(mode="python")
        intent = DeploymentIntent.model_validate(bom_raw)
        bom_mode = "generated_bom"
    else:
        workbook_intent = _infer_intent_from_workbooks(survey_path, context_path, network_layout_path)
        if workbook_intent is not None:
            inferred_intent = workbook_intent
            bom_mode = "inferred_from_workbook_bom"
        else:
            inferred_intent = infer_intent_from_inputs(survey_raw, context_raw, network_layout)
            bom_mode = "inferred_from_inputs"
        bom_raw = inferred_intent.model_dump(mode="python")
        intent = inferred_intent

    project = ProjectContext.model_validate(context_raw or {})

    provenance = [
        _ev("intake.survey", survey_raw, "read_key_value_file"),
        _ev("intake.bom", bom_raw, bom_mode),
        _ev("intake.project", context_raw, "read_key_value_file"),
    ]
    if workload_raw is not None:
        provenance.append(_ev("intake.workload", workload_raw, "read_key_value_file"))
    if network_layout is not None:
        provenance.append(_ev("intake.network_layout", network_layout, "parse_network_layout_workbook"))
    if invalid_bom_raw is not None:
        provenance.append(_ev("intake.bom_invalid", invalid_bom_raw, "deployment_intent_validation_failed"))

    normalized_inputs = {
        "survey": survey_raw,
        "bom": bom_raw,
        "project": context_raw,
    }
    if workload_raw is not None:
        normalized_inputs["workload"] = workload_raw
    if network_layout is not None:
        normalized_inputs["network_layout"] = {
            "vlans": network_layout.get("vlans", []),
            "cables": network_layout.get("cables", []),
        }

    return IntakeBundle(
        project=project,
        survey=survey,
        intent=intent,
        workload=workload,
        network_layout=network_layout,
        normalized_inputs=normalized_inputs,
        provenance=provenance,
    )
