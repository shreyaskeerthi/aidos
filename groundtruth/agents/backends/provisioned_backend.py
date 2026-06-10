"""Provisioned backend stub for NVIDIA Launchpad/NIM integration."""

from __future__ import annotations

from typing import Any

from groundtruth.agents.backends.base import BaseBackend


class ProvisionedBackend(BaseBackend):
    """Provisioned backend placeholder.

    This fails fast when required runtime configuration is missing so developers
    get a clear message before trying to call NIM services.
    """

    name = "provisioned"

    def __init__(self, *, nim_base_url: str, nim_api_key: str) -> None:
        self.nim_base_url = nim_base_url
        self.nim_api_key = nim_api_key

    def _validate_runtime(self) -> None:
        missing: list[str] = []
        if not self.nim_base_url:
            missing.append("NIM_BASE_URL")
        if not self.nim_api_key:
            missing.append("NIM_API_KEY")
        if missing:
            vars_text = ", ".join(missing)
            raise RuntimeError(
                "Provisioned mode is enabled but required environment variables "
                f"are missing: {vars_text}. Set these values or run with "
                "PROVISIONED_MODE=false for practice mode."
            )

    def generate_answer(
        self,
        *,
        query: str,
        objective: str,
        evidence: list[Any],
        readiness: dict[str, int],
        blockers: list[Any],
        next_actions: list[str],
        require_citations: bool,
    ) -> dict[str, Any]:
        self._validate_runtime()
        # Integration point for real NIM calls in provisioned environments.
        # Keep the return shape aligned with PracticeBackend.
        return {
            "answer": (
                "Provisioned backend stub reached with valid configuration. "
                "Connect this method to the NVIDIA NIM inference path."
            ),
            "citations": [match.source for match in evidence] if require_citations else [],
            "verified": bool(evidence),
            "backend_model": "nim-configured",
            "mode": self.name,
        }
