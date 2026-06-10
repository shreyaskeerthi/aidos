"""Backend selection for Darla runtime modes."""

from __future__ import annotations

from groundtruth.agents.backends.base import BaseBackend
from groundtruth.agents.backends.practice_backend import PracticeBackend
from groundtruth.agents.backends.provisioned_backend import ProvisionedBackend
from groundtruth.config.settings import DarlaSettings


def get_backend(settings: DarlaSettings) -> BaseBackend:
    """Return the inference backend chosen by centralized runtime settings."""
    if settings.provisioned_mode:
        return ProvisionedBackend(
            nim_base_url=settings.nim_base_url,
            nim_api_key=settings.nim_api_key,
        )
    return PracticeBackend(model_name=settings.practice_model_name)
