"""Conversational orchestration helpers for AIDOS operator interface."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aidos.orchestrator import query_artifacts
from aidos.schemas import ChatAnswer
from aidos.state_store import JsonStateStore


def _session_store_path(output_dir: str, session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"}) or "default"
    return Path(output_dir) / "state" / "chat_sessions" / f"{safe}.json"


def _append_turn(output_dir: str, session_id: str, role: str, message: str) -> None:
    store = JsonStateStore(_session_store_path(output_dir, session_id))
    payload = store.read()
    payload.setdefault("session_id", session_id)
    payload.setdefault("turns", [])
    payload["turns"].append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "message": message,
        }
    )
    store.write(payload)


def get_session(session_id: str, output_dir: str) -> dict:
    """Load persistent chat session state."""
    return JsonStateStore(_session_store_path(output_dir, session_id)).read()


def converse(message: str, output_dir: str, session_id: str = "default") -> ChatAnswer:
    """Grounded conversational response over lifecycle artifacts."""
    _append_turn(output_dir, session_id, "user", message)
    text = message.lower().strip()

    if text in {"hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening"}:
        answer = ChatAnswer(
            message=(
                "Welcome to AIDOS. I'm NeMoSys, the agentic operator runtime powered by the "
                "NemoClaw task graph. I can walk intake, validation, NetBox reconciliation, "
                "planning, execution, and verification for the current project."
            ),
            cited_artifacts=[],
            proposed_actions=["Upload survey, BOM, or workload files", "Run the project flow", "Ask about missing data"],
        )
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    if "do i have a bom" in text or "have a bom" in text:
        answer = ChatAnswer(
            message=(
                "AIDOS supports both paths through NeMoSys: provided BOM and generated BOM. "
                "If you have a BOM, provide bom_path. If not, provide workload_path "
                "and NeMoSys will deterministically draft one before validation."
            ),
            cited_artifacts=[],
            proposed_actions=["Run workflow with bom_path", "Run workflow with workload_path"],
        )
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    if "what is missing" in text or "missing" in text:
        answer = query_artifacts(output_dir, "missing_data_report missing fields")
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    if "runbook" in text:
        answer = query_artifacts(output_dir, "runbook task graph ansible")
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    if "netbox" in text:
        answer = query_artifacts(output_dir, "netbox payload site rack vlan")
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    if "failed" in text or "drift" in text or "verify" in text:
        answer = query_artifacts(output_dir, "verification drift critical warning")
        _append_turn(output_dir, session_id, "assistant", answer.message)
        return answer

    answer = query_artifacts(output_dir, message)
    _append_turn(output_dir, session_id, "assistant", answer.message)
    return answer
