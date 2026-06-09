"""Nemosys execution orchestration interfaces for AIDOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aidos.schemas import Evidence
from aidos.state_store import JsonStateStore


class ExecutionTask(BaseModel):
    """Normalized execution request routed through NCP."""

    task_id: str
    adapter: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    fallback_adapters: list[str] = Field(default_factory=list)
    approval_required: bool = True


class ApprovalRecord(BaseModel):
    """Persistent approval state for execution tasks."""

    task_id: str
    status: str = "pending"
    reviewer: str | None = None
    reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


class ApprovalStore:
    """File-backed approval state for Nemosys task execution gating."""

    def __init__(self, state_path: str | Path) -> None:
        self._store = JsonStateStore(state_path)

    def get(self, task_id: str) -> ApprovalRecord:
        payload = self._store.read()
        entry = payload.get(task_id)
        if isinstance(entry, dict):
            return ApprovalRecord.model_validate(entry)
        record = ApprovalRecord(task_id=task_id, status="pending")
        payload[task_id] = record.model_dump(mode="json")
        self._store.write(payload)
        return record

    def set(self, task_id: str, status: str, reviewer: str | None = None, reason: str | None = None) -> ApprovalRecord:
        record = ApprovalRecord(
            task_id=task_id,
            status=status,
            reviewer=reviewer,
            reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        payload = self._store.read()
        payload[task_id] = record.model_dump(mode="json")
        self._store.write(payload)
        return record

    def list(self) -> list[ApprovalRecord]:
        payload = self._store.read()
        return [ApprovalRecord.model_validate(item) for item in payload.values() if isinstance(item, dict)]


class NcpExecutor:
    """Nemosys Control Protocol executor with adapter registry."""

    def __init__(self, approval_store: ApprovalStore | None = None) -> None:
        self._adapters: dict[str, BaseAdapter] = {}
        self._approval_store = approval_store

    def register_adapter(self, name: str, adapter: BaseAdapter) -> None:
        self._adapters[name] = adapter

    def _missing_adapter_result(self, task: ExecutionTask, adapter_name: str) -> ExecutionResult:
        return ExecutionResult(
            task_id=task.task_id,
            status="failed",
            output={"error": f"No adapter registered for '{adapter_name}'"},
            evidence=[
                Evidence(
                    source="ncp.adapter_registry",
                    raw_value=adapter_name,
                    timestamp=datetime.now(timezone.utc),
                    context={"known_adapters": sorted(self._adapters.keys())},
                )
            ],
        )

    def run_task(self, task: ExecutionTask) -> ExecutionResult:
        if task.approval_required and self._approval_store is not None:
            approval = self._approval_store.get(task.task_id)
            if approval.status == "pending":
                return ExecutionResult(
                    task_id=task.task_id,
                    status="blocked_pending_approval",
                    output={"approval_status": approval.status},
                    evidence=[
                        Evidence(
                            source="ncp.approval",
                            raw_value=approval.model_dump(mode="json"),
                            timestamp=datetime.now(timezone.utc),
                            context={"task_id": task.task_id},
                            source_type="policy",
                            source_system="nemosys",
                            parser_or_adapter="approval_store",
                        )
                    ],
                )
            if approval.status == "rejected":
                return ExecutionResult(
                    task_id=task.task_id,
                    status="blocked_rejected",
                    output={"approval_status": approval.status, "reason": approval.reason},
                    evidence=[
                        Evidence(
                            source="ncp.approval",
                            raw_value=approval.model_dump(mode="json"),
                            timestamp=datetime.now(timezone.utc),
                            context={"task_id": task.task_id},
                            source_type="policy",
                            source_system="nemosys",
                            parser_or_adapter="approval_store",
                        )
                    ],
                )

        attempted: list[str] = []
        adapter_order = [task.adapter, *task.fallback_adapters]

        for adapter_name in adapter_order:
            adapter = self._adapters.get(adapter_name)
            result = self._missing_adapter_result(task, adapter_name) if adapter is None else adapter.execute(task.model_copy(update={"adapter": adapter_name}))
            attempted.append(adapter_name)
            if result.status in {"completed", "completed_with_warnings", "blocked_pending_approval", "blocked_rejected"}:
                result.output.setdefault("attempted_adapters", attempted)
                result.output.setdefault("adapter", adapter_name)
                return result

        final_result = result
        final_result.output.setdefault("attempted_adapters", attempted)
        return final_result
