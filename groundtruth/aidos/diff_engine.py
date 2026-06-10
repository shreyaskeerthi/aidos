"""Diff engine for EXPECTED vs OBSERVED drift detection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from groundtruth.aidos.schemas import (
    Evidence,
    ExpectedTruth,
    ObservedState,
    Severity,
    ValidationFinding,
)


def _evidence(key: str, observed_value: Any, expected_value: Any) -> list[Evidence]:
    return [
        Evidence(
            source=f"observed.{key}",
            raw_value=observed_value,
            timestamp=datetime.now(timezone.utc),
            context={"expected": expected_value},
        )
    ]


def compare_expected_vs_observed(
    expected: ExpectedTruth, observed: ObservedState
) -> list[ValidationFinding]:
    """Compare selected canonical fields and report deterministic drift findings."""

    checks: list[tuple[str, Any, Any]] = [
        ("gpu_model", expected.intent.gpu_model, observed.signals.get("gpu_model")),
        ("node_count", expected.intent.node_count, observed.signals.get("node_count")),
        ("uplinks", expected.site.uplinks, observed.signals.get("uplinks")),
        ("vlan_ids", expected.site.vlan_ids or expected.intent.required_vlans, observed.signals.get("vlan_ids")),
        ("liquid_cooling", expected.site.liquid_cooling, observed.signals.get("liquid_cooling")),
    ]

    findings: list[ValidationFinding] = []
    for key, expected_value, observed_value in checks:
        if observed_value is None:
            findings.append(
                ValidationFinding(
                    severity=Severity.WARNING,
                    code=f"OBSERVED_MISSING_{key.upper()}",
                    message=f"Observed state did not include '{key}'.",
                    recommendation="Collect fresh observed state data for drift analysis.",
                    evidence=_evidence(key, observed_value, expected_value),
                )
            )
            continue

        if str(observed_value).strip().lower() != str(expected_value).strip().lower():
            findings.append(
                ValidationFinding(
                    severity=Severity.WARNING,
                    code=f"DRIFT_{key.upper()}",
                    message=f"Expected '{key}' does not match observed state.",
                    recommendation="Review drift and reconcile intent/configuration with runtime.",
                    evidence=_evidence(key, observed_value, expected_value),
                )
            )
        else:
            findings.append(
                ValidationFinding(
                    severity=Severity.PASSED,
                    code=f"OBSERVED_MATCH_{key.upper()}",
                    message=f"Observed '{key}' matches expected state.",
                    recommendation="",
                    evidence=_evidence(key, observed_value, expected_value),
                )
            )

    return findings
