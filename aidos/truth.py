"""Canonical source-of-truth builder for AIDOS."""

from __future__ import annotations

from aidos.ingestion import IntakeBundle
from aidos.schemas import CanonicalSoT, ExpectedTruth


def build_canonical_sot(bundle: IntakeBundle) -> CanonicalSoT:
    """Formalize intake data into canonical source of truth."""
    expected = ExpectedTruth.from_inputs(bundle.survey, bundle.intent)
    return CanonicalSoT(
        project=bundle.project,
        intent=bundle.intent,
        site=bundle.survey,
        expected=expected,
        workload=bundle.workload,
        provenance=bundle.provenance,
    )
