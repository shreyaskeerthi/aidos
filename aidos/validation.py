"""Validation, completeness, and readiness evaluation for AIDOS."""

from __future__ import annotations

from aidos.diff_engine import compare_expected_vs_observed
from aidos.observed import parse_observed_state
from aidos.rules import run_validation_rules
from aidos.schemas import (
    CanonicalSoT,
    Evidence,
    MissingDataItem,
    MissingDataReport,
    Severity,
    ValidationReport,
)


def _summarize_missing(report: MissingDataReport) -> str:
    if not report.items:
        return "No missing data fields detected."
    return f"Missing data fields: {len(report.items)}"


def evaluate_missing_data(sot: CanonicalSoT) -> MissingDataReport:
    """Detect missing critical fields with deterministic checks."""
    items: list[MissingDataItem] = []

    checks = [
        ("site.loading_dock", sot.site.loading_dock),
        ("site.server_lift", sot.site.server_lift),
        ("site.available_circuits", sot.site.available_circuits),
        ("site.available_rack_slots", sot.site.available_rack_slots),
        ("site.available_power_kw", sot.site.available_power_kw),
        ("intent.gpu_model", sot.intent.gpu_model),
        ("intent.node_count", sot.intent.node_count),
    ]
    for field, value in checks:
        if value is None or value == "":
            items.append(
                MissingDataItem(
                    field=field,
                    reason="Value is missing from intake payload.",
                    severity=Severity.WARNING,
                    evidence=[
                        Evidence(
                            source=field,
                            raw_value=value,
                            source_type="sot",
                            source_system="aidos",
                            parser_or_adapter="missing-data-check",
                        )
                    ],
                )
            )

    report = MissingDataReport(items=items)
    report.summary = _summarize_missing(report)
    return report


def validate_sot(
    sot: CanonicalSoT,
    observed_path: str | None = None,
) -> tuple[ValidationReport, MissingDataReport]:
    """Run deterministic validation against SoT and optional observed state."""

    findings = run_validation_rules(sot.expected)
    if observed_path:
        observed = parse_observed_state(observed_path)
        findings.extend(compare_expected_vs_observed(sot.expected, observed))

    critical = [item for item in findings if item.severity == Severity.CRITICAL]
    warning = [item for item in findings if item.severity == Severity.WARNING]
    passed = [item for item in findings if item.severity == Severity.PASSED]

    if critical:
        readiness = "not_ready"
    elif warning:
        readiness = "ready_with_warnings"
    else:
        readiness = "ready"

    report = ValidationReport(
        deployment=sot.intent.deployment_name,
        critical=critical,
        warning=warning,
        passed=passed,
        readiness=readiness,
        summary=(
            f"Validation complete: {len(critical)} critical, "
            f"{len(warning)} warning, {len(passed)} passed. "
            f"Readiness={readiness}."
        ),
    )
    missing = evaluate_missing_data(sot)
    return report, missing
