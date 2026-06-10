"""Nemosys execution orchestration interfaces for AIDOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from groundtruth.aidos.schemas import Evidence


class ExecutionTask(BaseModel):
    """Normalized execution request routed through NCP."""

    task_id: str
    adapter: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True


class ExecutionResult(BaseModel):
    """Normalized execution result with auditable evidence."""

    task_id: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


class BaseAdapter(ABC):
    """Base adapter interface for API/CLI/MCP/browser execution."""

    @abstractmethod
    def execute(self, task: ExecutionTask) -> ExecutionResult:
        """Execute a task deterministically and return normalized output."""


class NcpExecutor:
    """Nemosys Control Protocol executor with adapter registry."""

    def __init__(self) -> None:
        self._adapters: dict[str, BaseAdapter] = {}

    def register_adapter(self, name: str, adapter: BaseAdapter) -> None:
        self._adapters[name] = adapter

    def run_task(self, task: ExecutionTask) -> ExecutionResult:
        adapter = self._adapters.get(task.adapter)
        if adapter is None:
            return ExecutionResult(
                task_id=task.task_id,
                status="failed",
                output={"error": f"No adapter registered for '{task.adapter}'"},
                evidence=[
                    Evidence(
                        source="ncp.adapter_registry",
                        raw_value=task.adapter,
                        timestamp=datetime.now(timezone.utc),
                        context={"known_adapters": sorted(self._adapters.keys())},
                    )
                ],
            )
        return adapter.execute(task)
