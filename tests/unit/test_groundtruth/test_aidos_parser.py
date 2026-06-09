from __future__ import annotations

from pathlib import Path

import pandas as pd

from aidos.parsers import parse_site_survey


def test_parse_site_survey_from_excel_field_value(monkeypatch, tmp_path: Path) -> None:
    survey_path = tmp_path / "survey.xlsx"
    survey_path.touch()

    frame = pd.DataFrame(
        {
            "Field": ["Loading Dock", "Server Lift", "Rack Floor PSF", "Available Rack Slots"],
            "Value": ["yes", "no", "180", "3"],
        }
    )

    monkeypatch.setattr(
        "aidos.parsers.pd.read_excel",
        lambda *_args, **_kwargs: {"Sheet1": frame},
    )

    survey, normalized = parse_site_survey(str(survey_path))

    assert survey.loading_dock is True
    assert survey.server_lift is False
    assert survey.rack_floor_psf == 180
    assert survey.available_rack_slots == 3
    assert normalized["loading_dock"] is True
