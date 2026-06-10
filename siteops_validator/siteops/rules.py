from __future__ import annotations

from typing import Any

from siteops.models import ValidationFinding


def _yes(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"yes", "true", "1"}


def _no(value: Any) -> bool:
    return value is False or str(value).strip().lower() in {"no", "false", "0"}


def evaluate_rules(site: dict[str, Any], bom: dict[str, Any]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    gpu_model = str(bom.get("gpu_model", "")).upper()
    node_count = int(bom.get("node_count", 0) or 0)

    if _no(site.get("server_lift")) and node_count >= 4:
        findings.append(
            ValidationFinding(
                severity="critical",
                code="PHYS_NO_LIFT",
                message="Server lift is unavailable for a dense node deployment.",
                recommendation="Arrange a rated server lift before installation window.",
            )
        )

    if _no(site.get("liquid_cooling")) and gpu_model in {"H100", "B200", "GB200"}:
        findings.append(
            ValidationFinding(
                severity="warning",
                code="THERMAL_AIR_ONLY",
                message=f"{gpu_model} deployment with air-only cooling may breach thermal envelope.",
                recommendation="Confirm thermal model or reduce rack density before cutover.",
            )
        )

    if _no(site.get("network_diagram_provided")):
        findings.append(
            ValidationFinding(
                severity="warning",
                code="NET_DIAGRAM_MISSING",
                message="No data center network diagram is attached.",
                recommendation="Provide a network diagram with VLAN and uplink paths.",
            )
        )

    if _no(site.get("layout_blueprint_provided")):
        findings.append(
            ValidationFinding(
                severity="warning",
                code="LAYOUT_MISSING",
                message="No rack layout blueprint is attached.",
                recommendation="Add rack and cable layout blueprint for install sequence.",
            )
        )

    vlan_needed = _yes(site.get("vlan_config_needed"))
    vlan_ids = site.get("vlan_ids") or []
    if vlan_needed and not vlan_ids:
        findings.append(
            ValidationFinding(
                severity="critical",
                code="VLAN_PLAN_MISSING",
                message="VLAN configuration is required but VLAN IDs are missing.",
                recommendation="Define required VLAN IDs and tagging plan before deployment.",
            )
        )

    if _yes(site.get("loading_dock")):
        findings.append(
            ValidationFinding(
                severity="passed",
                code="PHYS_DOCK_OK",
                message="Loading dock is available.",
                recommendation="",
            )
        )

    if _yes(site.get("available_circuits")):
        findings.append(
            ValidationFinding(
                severity="passed",
                code="POWER_CIRCUITS_OK",
                message="Dedicated circuits are available.",
                recommendation="",
            )
        )

    power_text = str(site.get("power", "")).lower()
    if "208" in power_text and "30" in power_text:
        findings.append(
            ValidationFinding(
                severity="passed",
                code="POWER_PROFILE_OK",
                message="Power profile includes 208V 30A capability.",
                recommendation="",
            )
        )

    rack_psf = site.get("rack_floor_psf")
    try:
        rack_psf_num = float(rack_psf)
    except (TypeError, ValueError):
        rack_psf_num = None
    if rack_psf_num is not None and rack_psf_num >= 150:
        findings.append(
            ValidationFinding(
                severity="passed",
                code="RACK_LOAD_OK",
                message="Rack floor load rating is at or above 150 psf.",
                recommendation="",
            )
        )

    uplinks = str(site.get("uplinks", "")).lower()
    if "10g" in uplinks:
        findings.append(
            ValidationFinding(
                severity="passed",
                code="UPLINK_PRESENT",
                message="10G uplink capability detected.",
                recommendation="",
            )
        )

    if _yes(site.get("ports_40g")):
        findings.append(
            ValidationFinding(
                severity="passed",
                code="PORT_40G_PRESENT",
                message="40G port availability detected.",
                recommendation="",
            )
        )

    return findings
