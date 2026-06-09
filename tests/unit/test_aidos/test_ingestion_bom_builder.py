from __future__ import annotations

import json
from pathlib import Path

from aidos.ingestion import ingest_inputs


def test_ingest_inputs_generates_bom_from_workload(tmp_path: Path) -> None:
    survey = {
        "loading_dock": "yes",
        "server_lift": "yes",
        "rack_floor_psf": 180,
        "available_circuits": "yes",
        "available_rack_slots": 4,
        "available_power_kw": 100,
        "available_cooling_kw": 90,
    }
    workload = {
        "workload_name": "rag-serving",
        "gpu_model_preference": "H100",
        "desired_node_count": 6,
    }

    survey_path = tmp_path / "survey.json"
    workload_path = tmp_path / "workload.json"
    survey_path.write_text(json.dumps(survey), encoding="utf-8")
    workload_path.write_text(json.dumps(workload), encoding="utf-8")

    bundle = ingest_inputs(str(survey_path), workload_path=str(workload_path))

    assert bundle.intent.gpu_model == "H100"
    assert bundle.intent.node_count == 6
    assert bundle.workload is not None
    assert "workload" in bundle.normalized_inputs
