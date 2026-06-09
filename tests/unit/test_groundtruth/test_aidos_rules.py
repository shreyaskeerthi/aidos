from __future__ import annotations

from aidos.rules import run_validation_rules
from aidos.schemas import DeploymentIntent, ExpectedTruth, SiteSurvey


def test_rules_are_deterministic_and_include_evidence() -> None:
    survey = SiteSurvey(
        loading_dock=False,
        server_lift=False,
        rack_floor_psf=120,
        liquid_cooling=False,
        available_circuits=False,
        vlan_config_needed=True,
        vlan_ids=[],
        available_rack_slots=1,
        available_power_kw=12,
        available_cooling_kw=10,
    )
    intent = DeploymentIntent(gpu_model="H100", node_count=8, deployment_name="lab-a")
    truth = ExpectedTruth.from_inputs(survey, intent)

    findings = run_validation_rules(truth)

    assert len(findings) >= 10
    assert any(item.severity.value == "critical" for item in findings)
    assert all(item.evidence for item in findings)
