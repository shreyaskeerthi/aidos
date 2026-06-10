from __future__ import annotations

from typing import Any

from siteops.models import ValidationFinding, ValidationReport
from siteops.rules import evaluate_rules


def build_deployment_plan(site: dict[str, Any], bom: dict[str, Any]) -> list[str]:
    gpu_model = bom.get("gpu_model", "unknown")
    return [
        f"Phase 1: Physical setup for {gpu_model} deployment and rack placement validation.",
        "Phase 2: Power validation (PDU redundancy and circuit isolation).",
        "Phase 3: Network setup (VLANs, uplinks, and switch/FI alignment).",
        "Phase 4: Platform configuration (fabric policies, cluster bootstrap settings).",
        "Phase 5: Post-deployment validation (GPU detection, VLAN reachability, cluster readiness).",
    ]


def generate_report(site: dict[str, Any], bom: dict[str, Any]) -> ValidationReport:
    findings = evaluate_rules(site, bom)

    report = ValidationReport(
        critical=[item for item in findings if item.severity == "critical"],
        warning=[item for item in findings if item.severity == "warning"],
        passed=[item for item in findings if item.severity == "passed"],
        deployment_plan=build_deployment_plan(site, bom),
    )

    report.summary = (
        f"Critical: {len(report.critical)}, Warning: {len(report.warning)}, "
        f"Passed: {len(report.passed)}"
    )
    return report


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    return report.to_dict()


def flatten_findings(report: ValidationReport) -> list[ValidationFinding]:
    return [*report.critical, *report.warning, *report.passed]
