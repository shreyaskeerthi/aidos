"""Conversational orchestration helpers for AIDOS operator interface."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

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


def _nemotron_api_key() -> str | None:
    return os.getenv("NVIDIA_API_KEY") or os.getenv("NGC_API_KEY")


def _nemotron_model() -> str:
    return os.getenv("AIDOS_CHAT_MODEL") or os.getenv(
        "APP_LLM_MODELNAME", "nvidia/nemotron-3-super-120b-a12b"
    )


def _nemotron_base_url() -> str:
    return os.getenv("AIDOS_CHAT_BASE_URL", "https://integrate.api.nvidia.com/v1")


def _artifact_context(output_dir: str, message: str) -> ChatAnswer:
    return query_artifacts(output_dir, message)


def _recent_turns(output_dir: str, session_id: str, limit: int = 6) -> list[dict[str, str]]:
    session = get_session(session_id, output_dir)
    turns = session.get("turns", []) if isinstance(session, dict) else []
    history: list[dict[str, str]] = []
    for turn in turns[-limit:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "user")
        content = str(turn.get("message") or "").strip()
        if not content:
            continue
        history.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    return history


def _ask_nemotron(output_dir: str, session_id: str, message: str) -> ChatAnswer:
    grounding = _artifact_context(output_dir, message)
    api_key = _nemotron_api_key()
    if not api_key:
        return grounding

    artifact_summary = grounding.message
    cited = grounding.cited_artifacts
    actions = grounding.proposed_actions

    system_prompt = (
        "You are NeMoSys, the AIDOS operator assistant. Answer user questions about "
        "intake, NetBox sync, validation, planning, execution, and deployment state. "
        "Use the provided artifact context as the source of truth. If the artifact "
        "context is incomplete, say what is missing instead of inventing facts. Keep "
        "answers concise and operational."
    )
    user_prompt = (
        f"Artifact context:\n{artifact_summary}\n\n"
        f"User question: {message}\n\n"
        "Answer as NeMoSys. Mention concrete deployment objects when available."
    )

    payload = {
        "model": _nemotron_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            *_recent_turns(output_dir, session_id),
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 700,
    }

    try:
        with httpx.Client(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as client:
            response = client.post(
                f"{_nemotron_base_url().rstrip('/')}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        return grounding

    content = ""
    choices = data.get("choices", []) if isinstance(data, dict) else []
    if choices and isinstance(choices[0], dict):
        message_payload = choices[0].get("message", {})
        if isinstance(message_payload, dict):
            content = str(message_payload.get("content") or "").strip()

    if not content:
        return grounding

    return ChatAnswer(
        message=content,
        cited_artifacts=cited,
        proposed_actions=actions,
    )


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

    answer = _ask_nemotron(output_dir, session_id, message)
    _append_turn(output_dir, session_id, "assistant", answer.message)
    return answer
