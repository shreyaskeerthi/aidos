"""Deterministic rule engine for AIDOS validation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from groundtruth.aidos.schemas import Evidence, ExpectedTruth, Severity, ValidationFinding


def _ev(source: str, raw_value: Any, context: dict[str, Any] | None = None) -> Evidence:
    return Evidence(
        source=source,
        raw_value=raw_value,
        timestamp=datetime.now(timezone.utc),
        context=context or {},
    )


def _result(
    severity: Severity,
    code: str,
    message: str,
    recommendation: str,
    evidence: list[Evidence],
) -> ValidationFinding:
    return ValidationFinding(
        severity=severity,
        code=code,
        message=message,
        recommendation=recommendation,
        evidence=evidence,
    )


def run_validation_rules(truth: ExpectedTruth) -> list[ValidationFinding]:
    """Run deterministic infrastructure validation rules."""
    site = truth.site
    intent = truth.intent

    findings: list[ValidationFinding] = []

    findings.append(
        _result(
            Severity.PASSED if intent.node_count > 0 else Severity.CRITICAL,
            "INTENT_NODE_COUNT_VALID",
            "Node count is a positive integer."
            if intent.node_count > 0
            else "Node count must be greater than zero.",
            "Set node_count >= 1 in BOM.",
            [_ev("intent.node_count", intent.node_count)],
        )
    )

    findings.append(
        _result(
            Severity.PASSED if site.loading_dock is True else Severity.CRITICAL,
            "REAL_LOADING_DOCK",
            "Loading dock is available."
            if site.loading_dock is True
            else "Loading dock is not confirmed for hardware delivery.",
            "Confirm loading dock access before delivery window.",
            [_ev("survey.loading_dock", site.loading_dock)],
        )
    )

    dense_install = intent.node_count >= 4
    has_lift = site.server_lift is True
    findings.append(
        _result(
            Severity.PASSED if (not dense_install or has_lift) else Severity.CRITICAL,
            "REAL_SERVER_LIFT",
            "Server lift requirements are satisfied."
            if (not dense_install or has_lift)
            else "Dense deployment requires a rated server lift.",
            "Provide a rated server lift or reduce per-rack density.",
            [_ev("survey.server_lift", site.server_lift, {"dense_install": dense_install})],
        )
    )

    rack_psf = site.rack_floor_psf
    meets_floor_load = rack_psf is not None and rack_psf >= 150
    findings.append(
        _result(
            Severity.PASSED if meets_floor_load else Severity.CRITICAL,
            "REAL_FLOOR_LOAD",
            "Floor load rating meets minimum 150 psf."
            if meets_floor_load
            else "Floor load rating is missing or below 150 psf.",
            "Validate structural floor load or move deployment zone.",
            [_ev("survey.rack_floor_psf", rack_psf)],
        )
    )

    findings.append(
        _result(
            Severity.PASSED if site.available_circuits is True else Severity.CRITICAL,
            "REAL_POWER_CIRCUITS",
            "Dedicated power circuits are available."
            if site.available_circuits is True
            else "Dedicated power circuits are not confirmed.",
            "Provision dedicated circuits before install.",
            [_ev("survey.available_circuits", site.available_circuits)],
        )
    )

    profile = (site.power_profile or "").lower()
    has_datacenter_profile = "208" in profile and "30" in profile
    findings.append(
        _result(
            Severity.PASSED if has_datacenter_profile else Severity.WARNING,
            "REAL_POWER_PROFILE",
            "Power profile includes 208V 30A characteristics."
            if has_datacenter_profile
            else "Power profile does not clearly state 208V/30A capability.",
            "Verify power profile against rack PDU and node draw.",
            [_ev("survey.power_profile", site.power_profile)],
        )
    )

    liquid_required = truth.high_density_gpu
    has_liquid = site.liquid_cooling is True
    findings.append(
        _result(
            Severity.PASSED if (not liquid_required or has_liquid) else Severity.WARNING,
            "REAL_COOLING_MODE",
            "Cooling mode aligns with GPU thermal density."
            if (not liquid_required or has_liquid)
            else "High-density GPU deployment is not marked as liquid-cooled.",
            "Confirm thermal envelope or enable liquid cooling path.",
            [_ev("survey.liquid_cooling", site.liquid_cooling, {"gpu_model": intent.gpu_model})],
        )
    )

    findings.append(
        _result(
            Severity.PASSED
            if site.network_diagram_provided is True
            else Severity.WARNING,
            "REAL_NETWORK_DIAGRAM",
            "Network diagram is present."
            if site.network_diagram_provided is True
            else "Network diagram is missing.",
            "Attach an L2/L3 diagram with VLAN and uplink paths.",
            [_ev("survey.network_diagram_provided", site.network_diagram_provided)],
        )
    )

    findings.append(
        _result(
            Severity.PASSED
            if site.layout_blueprint_provided is True
            else Severity.WARNING,
            "REAL_LAYOUT_BLUEPRINT",
            "Rack layout blueprint is present."
            if site.layout_blueprint_provided is True
            else "Rack layout blueprint is missing.",
            "Provide rack position and cabling blueprint.",
            [_ev("survey.layout_blueprint_provided", site.layout_blueprint_provided)],
        )
    )

    vlan_needed = site.vlan_config_needed is True
    vlans = site.vlan_ids or intent.required_vlans
    findings.append(
        _result(
            Severity.PASSED if (not vlan_needed or bool(vlans)) else Severity.CRITICAL,
            "REAL_VLAN_PLAN",
            "VLAN plan is available when required."
            if (not vlan_needed or bool(vlans))
            else "VLAN configuration is required but VLAN IDs are missing.",
            "Define required VLAN IDs and tagging/trunk strategy.",
            [_ev("survey.vlan_ids", vlans, {"vlan_config_needed": vlan_needed})],
        )
    )

    uplinks = (site.uplinks or "").lower()
    has_uplink = any(speed in uplinks for speed in ("10g", "25g", "40g", "100g"))
    findings.append(
        _result(
            Severity.PASSED if has_uplink else Severity.WARNING,
            "REAL_UPLINK_CAPACITY",
            "Uplink capacity is declared."
            if has_uplink
            else "Uplink capacity is not clearly declared.",
            "Confirm uplink count and speed per rack leaf.",
            [_ev("survey.uplinks", site.uplinks)],
        )
    )

    forty_g_required = intent.node_count >= 8
    forty_g_available = site.ports_40g is True
    findings.append(
        _result(
            Severity.PASSED if (not forty_g_required or forty_g_available) else Severity.WARNING,
            "REAL_40G_PORTS",
            "40G port requirements are satisfied."
            if (not forty_g_required or forty_g_available)
            else "Large node count deployment may require 40G ports.",
            "Validate switch port speed and breakout plan.",
            [_ev("survey.ports_40g", site.ports_40g, {"node_count": intent.node_count})],
        )
    )

    rack_slots = site.available_rack_slots
    sufficient_slots = rack_slots is not None and rack_slots >= truth.required_rack_slots
    findings.append(
        _result(
            Severity.PASSED if sufficient_slots else Severity.CRITICAL,
            "REAL_RACK_SLOTS",
            "Available rack slots satisfy deployment plan."
            if sufficient_slots
            else "Rack slot availability is missing or below requirement.",
            "Increase rack allocation or reduce initial rollout size.",
            [
                _ev(
                    "survey.available_rack_slots",
                    rack_slots,
                    {"required_rack_slots": truth.required_rack_slots},
                )
            ],
        )
    )

    available_power = site.available_power_kw
    power_ok = available_power is not None and available_power >= truth.estimated_power_kw
    findings.append(
        _result(
            Severity.PASSED if power_ok else Severity.CRITICAL,
            "REAL_POWER_BUDGET",
            "Available power budget meets estimated draw."
            if power_ok
            else "Available power budget is missing or below estimated draw.",
            "Increase available power capacity before deployment.",
            [
                _ev(
                    "survey.available_power_kw",
                    available_power,
                    {"estimated_power_kw": truth.estimated_power_kw},
                )
            ],
        )
    )

    available_cooling = site.available_cooling_kw
    cooling_ok = available_cooling is not None and available_cooling >= truth.estimated_cooling_kw
    findings.append(
        _result(
            Severity.PASSED if cooling_ok else Severity.WARNING,
            "REAL_COOLING_BUDGET",
            "Available cooling budget meets estimated thermal output."
            if cooling_ok
            else "Cooling budget is missing or below estimated thermal output.",
            "Increase cooling capacity or reduce rack density.",
            [
                _ev(
                    "survey.available_cooling_kw",
                    available_cooling,
                    {"estimated_cooling_kw": truth.estimated_cooling_kw},
                )
            ],
        )
    )

    return findings
