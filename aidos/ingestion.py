"""Ingestion and BOM-builder workflows for AIDOS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aidos.parsers import read_key_value_file
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


def ingest_inputs(
    survey_path: str,
    *,
    bom_path: str | None = None,
    workload_path: str | None = None,
    context_path: str | None = None,
) -> IntakeBundle:
    """Ingest intake artifacts supporting BOM and no-BOM starting conditions."""

    survey_raw = read_key_value_file(survey_path)
    survey = SiteSurvey.model_validate(survey_raw)

    workload: WorkloadProfile | None = None
    workload_raw: dict[str, Any] | None = None
    if workload_path:
        workload_raw = read_key_value_file(workload_path)
        workload = WorkloadProfile.model_validate(workload_raw)

    if bom_path:
        bom_raw = read_key_value_file(bom_path)
        intent = DeploymentIntent.model_validate(bom_raw)
        bom_mode = "provided_bom"
    elif workload is not None:
        bom_raw = build_bom_from_workload(workload).model_dump(mode="python")
        intent = DeploymentIntent.model_validate(bom_raw)
        bom_mode = "generated_bom"
    else:
        raise ValueError("Provide either bom_path or workload_path.")

    context_raw = read_key_value_file(context_path) if context_path else {}
    project = ProjectContext.model_validate(context_raw or {})

    provenance = [
        _ev("intake.survey", survey_raw, "read_key_value_file"),
        _ev("intake.bom", bom_raw, bom_mode),
        _ev("intake.project", context_raw, "read_key_value_file"),
    ]
    if workload_raw is not None:
        provenance.append(_ev("intake.workload", workload_raw, "read_key_value_file"))

    normalized_inputs = {
        "survey": survey_raw,
        "bom": bom_raw,
        "project": context_raw,
    }
    if workload_raw is not None:
        normalized_inputs["workload"] = workload_raw

    return IntakeBundle(
        project=project,
        survey=survey,
        intent=intent,
        workload=workload,
        normalized_inputs=normalized_inputs,
        provenance=provenance,
    )
