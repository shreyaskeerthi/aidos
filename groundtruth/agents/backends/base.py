"""Base backend interface for Darla inference backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBackend(ABC):
    """Interface that all Darla inference backends must implement."""

    name: str = "base"

    @abstractmethod
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
        """Generate an answer using the selected backend."""
