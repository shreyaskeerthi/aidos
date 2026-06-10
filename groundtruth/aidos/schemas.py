"""Schemas for the AIDOS control-plane MVP."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """Deterministic finding severities."""

    CRITICAL = "critical"
    WARNING = "warning"
    PASSED = "passed"


class Evidence(BaseModel):
    """Auditable evidence attached to a finding or action."""

    source: str
    raw_value: Any
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class ValidationFinding(BaseModel):
    """A deterministic validation result."""

    severity: Severity
    code: str
    message: str
    recommendation: str
    evidence: list[Evidence]


class SiteSurvey(BaseModel):
    """Canonical representation of parsed site survey inputs."""

    model_config = ConfigDict(extra="allow")

    loading_dock: bool | None = None
    server_lift: bool | None = None
    rack_floor_psf: float | None = None
    liquid_cooling: bool | None = None
    power_profile: str | None = None
    available_circuits: bool | None = None
    uplinks: str | None = None
    ports_40g: bool | None = None
    vlan_config_needed: bool | None = None
    vlan_ids: list[str] = Field(default_factory=list)
    network_diagram_provided: bool | None = None
    layout_blueprint_provided: bool | None = None
    available_rack_slots: int | None = None
    available_power_kw: float | None = None
    available_cooling_kw: float | None = None


class DeploymentIntent(BaseModel):
    """Canonical representation of expected deployment intent from BOM/config."""

    model_config = ConfigDict(extra="allow")

    deployment_name: str = "aidos-deployment"
    gpu_model: str
    node_count: int = 1
    target_platform: str | None = None
    required_vlans: list[str] = Field(default_factory=list)


class ExpectedTruth(BaseModel):
    """Derived source of truth from intent and reality constraints."""

    site: SiteSurvey
    intent: DeploymentIntent
    required_rack_slots: int
    estimated_power_kw: float
    estimated_cooling_kw: float
    high_density_gpu: bool

    @staticmethod
    def from_inputs(site: SiteSurvey, intent: DeploymentIntent) -> "ExpectedTruth":
        power_kw_per_node = {
            "H100": 10.0,
            "H200": 10.5,
            "B200": 12.0,
            "GB200": 15.0,
        }
        cooling_kw_per_node = {
            "H100": 9.0,
            "H200": 9.5,
            "B200": 11.0,
            "GB200": 14.0,
        }
        model = intent.gpu_model.upper().strip()
        power_factor = power_kw_per_node.get(model, 7.0)
        cooling_factor = cooling_kw_per_node.get(model, 6.0)
        return ExpectedTruth(
            site=site,
            intent=intent,
            required_rack_slots=ceil(max(intent.node_count, 1) / 4),
            estimated_power_kw=power_factor * max(intent.node_count, 1),
            estimated_cooling_kw=cooling_factor * max(intent.node_count, 1),
            high_density_gpu=model in {"H100", "H200", "B200", "GB200"},
        )


class ObservedState(BaseModel):
    """Normalized runtime observed state from CLI/API outputs."""

    source: str
    signals: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Top-level deterministic report."""

    deployment: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    critical: list[ValidationFinding] = Field(default_factory=list)
    warning: list[ValidationFinding] = Field(default_factory=list)
    passed: list[ValidationFinding] = Field(default_factory=list)
    readiness: str = "not_ready"
    summary: str = ""


class AidosValidationOutput(BaseModel):
    """Combined payload returned by AIDOS validation service."""

    normalized_survey: dict[str, Any]
    normalized_bom: dict[str, Any]
    report: ValidationReport
