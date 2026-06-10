"""Runtime settings for Darla."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class DarlaSettings:
    provisioned_mode: bool
    nim_base_url: str
    nim_api_key: str
    practice_model_name: str


def load_settings() -> DarlaSettings:
    """Load Darla runtime settings from environment variables."""
    return DarlaSettings(
        provisioned_mode=_to_bool(os.getenv("PROVISIONED_MODE", "false")),
        nim_base_url=os.getenv("NIM_BASE_URL", "").strip(),
        nim_api_key=os.getenv("NIM_API_KEY", "").strip(),
        practice_model_name=os.getenv(
            "PRACTICE_MODEL_NAME", "darla-practice-deterministic"
        ),
    )
