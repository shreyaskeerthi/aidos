"""Service orchestration for AIDOS deterministic validation."""

from __future__ import annotations

from aidos.diff_engine import compare_expected_vs_observed
from aidos.observed import parse_observed_state
from aidos.parsers import parse_bom, parse_site_survey
from aidos.rules import run_validation_rules
from aidos.schemas import AidosValidationOutput, ExpectedTruth, Severity, ValidationReport


def _build_summary(report: ValidationReport) -> str:
    return (
        "Validation complete: "
        f"{len(report.critical)} critical, "
        f"{len(report.warning)} warning, "
        f"{len(report.passed)} passed. "
        f"Readiness={report.readiness}."
    )


def _readiness(critical_count: int, warning_count: int) -> str:
    if critical_count > 0:
        return "not_ready"
    if warning_count > 0:
        return "ready_with_warnings"
    return "ready"


def validate_deployment(
    survey_path: str,
    bom_path: str,
    observed_path: str | None = None,
) -> AidosValidationOutput:
    """Run AIDOS deterministic validation pipeline."""

    survey, normalized_survey = parse_site_survey(survey_path)
    intent, normalized_bom = parse_bom(bom_path)
    truth = ExpectedTruth.from_inputs(survey, intent)

    findings = run_validation_rules(truth)
    if observed_path:
        observed = parse_observed_state(observed_path)
        findings.extend(compare_expected_vs_observed(truth, observed))

    critical = [item for item in findings if item.severity == Severity.CRITICAL]
    warning = [item for item in findings if item.severity == Severity.WARNING]
    passed = [item for item in findings if item.severity == Severity.PASSED]

    report = ValidationReport(
        deployment=intent.deployment_name,
        critical=critical,
        warning=warning,
        passed=passed,
        readiness=_readiness(len(critical), len(warning)),
    )
    report.summary = _build_summary(report)

    return AidosValidationOutput(
        normalized_survey=normalized_survey,
        normalized_bom=normalized_bom,
        report=report,
    )
