"""Darla agent pipeline built on local GroundTruth documents."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

from groundtruth.agents.backend_factory import get_backend
from groundtruth.config.settings import DarlaSettings, load_settings

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "with",
    "you",
}


@dataclass(slots=True)
class EvidenceMatch:
    source: str
    score: int
    snippets: list[str]


@dataclass(slots=True)
class Blocker:
    category: str
    severity: str
    message: str


@dataclass(slots=True)
class DarlaResult:
    project: str
    subtitle: str
    timestamp_utc: str
    customer_ask: str
    objective: str
    readiness: dict[str, int]
    blockers: list[Blocker]
    evidence: list[EvidenceMatch]
    next_actions: list[str]
    confidence: int
    policies: dict[str, Any]
    backend_mode: str
    backend_model: str
    answer: str
    citations: list[str]
    verified: bool
    source_attribution: list[dict[str, Any]]
    confidence_breakdown: dict[str, Any]
    ui_sections: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["average_readiness"] = average_score(self.readiness)
        return payload


def average_score(scores: dict[str, int]) -> int:
    return int(sum(scores.values()) / max(1, len(scores)))


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-]+", text.lower())
        if token not in STOP_WORDS and len(token) > 2
    ]


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def load_darla_config(config_dir: Path) -> dict[str, Any]:
    json_path = config_dir / "darla.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))

    yaml_path = config_dir / "darla.yaml"
    if yaml is not None and yaml_path.exists():
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    raise FileNotFoundError("No Darla config file found in groundtruth/config.")


def load_groundtruth_documents(data_dir: Path) -> dict[str, str]:
    documents: dict[str, str] = {}
    for path in sorted(data_dir.glob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".md", ".txt", ".json"}:
            documents[path.name] = path.read_text(encoding="utf-8")
    return documents


def intake_agent(customer_ask: str) -> dict[str, str]:
    cleaned = re.sub(r"\s+", " ", customer_ask.strip())
    objective = cleaned if len(cleaned) <= 220 else cleaned[:217] + "..."
    return {"raw": cleaned, "objective": objective}


def retrieve_evidence(
    customer_ask: str,
    documents: dict[str, str],
    retrieval_config: dict[str, Any],
) -> list[EvidenceMatch]:
    query_tokens = _tokenize(customer_ask)
    query_counter = Counter(query_tokens)
    matches: list[EvidenceMatch] = []

    for source, content in documents.items():
        snippets: list[tuple[int, str]] = []
        for sentence in _split_sentences(content):
            sentence_tokens = _tokenize(sentence)
            overlap = sum((query_counter & Counter(sentence_tokens)).values())
            if overlap > 0:
                snippets.append((overlap, sentence))

        score = sum(points for points, _ in snippets)
        if score >= int(retrieval_config["min_score"]):
            top_snippets = [
                sentence
                for _, sentence in sorted(snippets, key=lambda item: item[0], reverse=True)[
                    : int(retrieval_config["max_snippets_per_source"])
                ]
            ]
            matches.append(EvidenceMatch(source=source, score=score, snippets=top_snippets))

    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[: int(retrieval_config["max_evidence"])]


def readiness_agent(
    intake: dict[str, str],
    evidence: list[EvidenceMatch],
    config: dict[str, Any],
) -> dict[str, int]:
    scores, _ = readiness_insight_agent(intake, evidence, config)
    return scores


def readiness_insight_agent(
    intake: dict[str, str],
    evidence: list[EvidenceMatch],
    config: dict[str, Any],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    scoring = config["scoring"]
    categories: dict[str, list[str]] = scoring["categories"]
    combined_text = " ".join(
        [intake["raw"]] + [snippet for match in evidence for snippet in match.snippets]
    ).lower()

    scores: dict[str, int] = {}
    feedback: list[dict[str, Any]] = []
    for category, keywords in categories.items():
        hits = sum(1 for keyword in keywords if keyword.lower() in combined_text)
        matched_keywords = [
            keyword for keyword in keywords if keyword.lower() in combined_text
        ]
        evidence_sources = [
            match.source
            for match in evidence
            if any(keyword.lower() in " ".join(match.snippets).lower() for keyword in keywords)
        ]
        evidence_hits = len(evidence_sources)
        score = int(scoring["base_score"])
        score += min(hits, 3) * int(scoring["keyword_bonus"])
        if evidence_hits:
            score += int(scoring["evidence_bonus"])
        score = min(int(scoring["max_score"]), score)
        scores[category] = score

        reasons: list[str] = []
        if matched_keywords:
            reasons.append(
                "Keyword signals: " + ", ".join(matched_keywords[:3])
            )
        else:
            reasons.append("No direct keyword signal detected in ask or matched snippets")

        if evidence_sources:
            reasons.append(
                f"Evidence support found in {len(evidence_sources)} source(s)"
            )
        else:
            reasons.append("No supporting evidence snippet mapped to this category")

        if score < 65:
            reasons.append("Below deployment confidence threshold")

        trend = "up" if score >= 80 else ("flat" if score >= 65 else "down")
        feedback.append(
            {
                "category": category,
                "score": score,
                "status": _score_status(score),
                "confidence": _score_confidence(score),
                "trend": trend,
                "reasons": reasons,
            }
        )

    return scores, feedback


def thinking_layer_agent(
    intake: dict[str, str],
    readiness: dict[str, int],
    blockers: list[Blocker],
    evidence: list[EvidenceMatch],
    next_actions: list[str],
    readiness_feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    decomposition = [
        "Extract objective and constraints",
        "Evaluate readiness categories",
        "Retrieve and rank evidence",
        "Assess risk and blockers",
        "Generate prioritized next actions",
    ]

    weakest_categories = sorted(readiness.items(), key=lambda item: item[1])[:3]
    decisions = [
        f"{category} is a priority risk at {score}/100"
        for category, score in weakest_categories
    ]
    if not decisions:
        decisions.append("No critical category risks detected")

    priorities = next_actions[:3] or [
        "Confirm deployment target",
        "Validate ownership and timeline",
        "Generate stakeholder alignment brief",
    ]

    justification: list[str] = []
    for blocker in blockers[:3]:
        justification.append(
            f"{blocker.category} flagged as {blocker.severity} risk"
        )
    if len(evidence) < 3:
        justification.append("Evidence depth is limited; additional grounding advised")
    if not blockers:
        justification.append("No blocker crossed the escalation threshold")

    return {
        "decomposition": decomposition,
        "decisions": decisions,
        "priorities": priorities,
        "justification": justification,
        "category_feedback": readiness_feedback,
        "agent_mapping": {
            "Intake Agent": decomposition[0],
            "Readiness Agent": decomposition[1],
            "Evidence Agent": decomposition[2],
            "Risk Agent": decomposition[3],
            "Output Composer": decomposition[4],
        },
        "ask_excerpt": intake.get("objective", ""),
    }


def risk_agent(readiness: dict[str, int]) -> list[Blocker]:
    blockers: list[Blocker] = []
    for category, score in readiness.items():
        if score >= 75:
            continue
        severity = "high" if score < 60 else "medium"
        blockers.append(
            Blocker(
                category=category,
                severity=severity,
                message=(
                    f"{category} readiness is {score}/100. Darla needs stronger proof "
                    "before this can be presented as deployment-ready."
                ),
            )
        )
    return blockers


def next_actions_agent(
    readiness: dict[str, int],
    config: dict[str, Any],
) -> list[str]:
    actions_config: dict[str, list[str]] = config["actions"]
    ordered_categories = sorted(readiness.items(), key=lambda item: item[1])
    actions: list[str] = []
    for category, _ in ordered_categories:
        for action in actions_config.get(category, []):
            if action not in actions:
                actions.append(action)
        if len(actions) >= 6:
            break
    return actions[:6]


def confidence_agent(
    readiness: dict[str, int],
    evidence: list[EvidenceMatch],
    policies: dict[str, Any],
) -> int:
    confidence = average_score(readiness)
    confidence += min(len(evidence), 3) * 4
    if policies.get("require_citations") and evidence:
        confidence += 4
    return max(40, min(96, confidence))


def _score_status(score: int) -> str:
    if score >= 80:
        return "green"
    if score >= 65:
        return "yellow"
    return "red"


def _score_confidence(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 65:
        return "Medium"
    return "Low"


def _readiness_label(score: int) -> str:
    if score >= 80:
        return "STRONG READINESS"
    if score >= 65:
        return "MODERATE READINESS"
    return "LOW READINESS"


def stakeholders_agent(
    intake: dict[str, str],
    readiness: dict[str, int],
) -> dict[str, Any]:
    text = intake["raw"].lower()
    role_rules = {
        "Executive Sponsor": ["sponsor", "executive", "vp", "director"],
        "Technical Owner": ["technical owner", "architect", "engineering", "platform"],
        "Security Owner": ["security", "compliance", "governance", "ciso"],
        "Delivery Lead": ["delivery", "program manager", "project manager", "implementation"],
    }

    stakeholders: dict[str, dict[str, str]] = {}
    missing_roles: list[str] = []
    for role, keywords in role_rules.items():
        matched = any(keyword in text for keyword in keywords)
        status = "green" if matched else "red"
        note = "Identified" if matched else "Missing"

        if role == "Security Owner" and not matched and readiness.get("Security", 0) >= 65:
            status = "yellow"
            note = "Partial"

        if status == "red":
            missing_roles.append(role)
        stakeholders[role] = {"status": status, "note": note}

    risk_callout = (
        "No executive sponsor -> high failure risk"
        if stakeholders["Executive Sponsor"]["status"] == "red"
        else "Executive sponsorship signal detected"
    )

    return {
        "stakeholders": stakeholders,
        "missing_roles": missing_roles,
        "risk_callout": risk_callout,
    }


def timeline_agent(readiness: dict[str, int]) -> dict[str, Any]:
    phase_scores = {
        "Discovery": readiness.get("Business", 0),
        "Data Ingestion": readiness.get("Data", 0),
        "Security Validation": readiness.get("Security", 0),
        "POC Execution (2 weeks)": int(
            (
                readiness.get("Infrastructure", 0)
                + readiness.get("Ownership", 0)
                + readiness.get("Timeline", 0)
            )
            / 3
        ),
    }

    phases: list[dict[str, Any]] = []
    missing_proof: list[str] = []
    for name, score in phase_scores.items():
        status = _score_status(score)
        confidence = _score_confidence(score)
        if status != "green":
            missing_proof.append(name)
        phases.append(
            {
                "phase": name,
                "status": status,
                "confidence": confidence,
                "score": score,
            }
        )

    return {"phases": phases, "missing_proof": missing_proof}


def evidence_mapping_agent(
    evidence: list[EvidenceMatch],
    categories: dict[str, list[str]],
) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for match in evidence:
        snippet_text = " ".join(match.snippets).lower()
        impacted_categories = [
            category
            for category, keywords in categories.items()
            if any(keyword.lower() in snippet_text for keyword in keywords)
        ]
        documents.append(
            {
                "source": match.source,
                "score": match.score,
                "top_snippet": match.snippets[0] if match.snippets else "",
                "impacted_categories": impacted_categories,
            }
        )

    return {"documents": documents}


def agent_flow_agent(thinking: dict[str, Any]) -> dict[str, Any]:
    decisions = thinking.get("decisions", [])
    justification = thinking.get("justification", [])
    priorities = thinking.get("priorities", [])
    mapping = thinking.get("agent_mapping", {})

    steps = [
        {
            "name": "Intake Agent",
            "status": "done",
            "duration_ms": 16,
            "persona": "Program discovery lead",
            "background": "Customer discovery and scope framing",
            "summary": "Normalize the customer ask into a structured prompt and capture the intent signal.",
            "did": mapping.get("Intake Agent", "Extract objective and constraints"),
            "concluded": "Objective is normalized and ready for category scoring",
            "why": [
                thinking.get("ask_excerpt", "Customer ask parsed"),
                "Structured ask is required before scoring and retrieval",
            ],
            "inputs": ["raw ask text"],
            "outputs": ["normalized intent", "key terms"],
            "transcript": [
                {
                    "speaker": "Intake Agent",
                    "message": "I converted the ask into explicit outcomes, constraints, and success criteria.",
                },
                {
                    "speaker": "Intake Agent",
                    "message": "Handing off normalized intent to Readiness Agent for scoring.",
                },
            ],
        },
        {
            "name": "Readiness Agent",
            "status": "done",
            "duration_ms": 28,
            "persona": "Delivery architect",
            "background": "Implementation readiness assessment",
            "summary": "Score each readiness category and identify where the project is blocked.",
            "did": mapping.get("Readiness Agent", "Evaluate readiness categories"),
            "concluded": decisions[0] if decisions else "No readiness risks identified",
            "why": justification[:2] or ["Readiness and confidence thresholds drive escalation"],
            "inputs": ["intake payload", "evidence matches"],
            "outputs": ["readiness scores", "blocker list"],
            "transcript": [
                {
                    "speaker": "Readiness Agent",
                    "message": "Computed category-level readiness and highlighted weak signals.",
                },
                {
                    "speaker": "Readiness Agent",
                    "message": "Escalating low-confidence categories to Risk Agent.",
                },
            ],
        },
        {
            "name": "Risk Agent",
            "status": "done",
            "duration_ms": 12,
            "persona": "Risk and compliance analyst",
            "background": "Operational and governance risk triage",
            "summary": "Translate low scores into concrete risk language the team can act on.",
            "did": mapping.get("Risk Agent", "Assess risk and blockers"),
            "concluded": decisions[1] if len(decisions) > 1 else "Risk profile captured",
            "why": justification or ["Escalation policy is triggered for low-readiness categories"],
            "inputs": ["readiness scores"],
            "outputs": ["risk summary", "escalation notes"],
            "transcript": [
                {
                    "speaker": "Risk Agent",
                    "message": "Mapped low-readiness areas to concrete delivery and governance risks.",
                },
                {
                    "speaker": "Risk Agent",
                    "message": "Passing prioritized blocker list to Evidence Agent for source grounding.",
                },
            ],
        },
        {
            "name": "Evidence Agent",
            "status": "done",
            "duration_ms": 31,
            "persona": "Retrieval specialist",
            "background": "Evidence grounding and citation quality",
            "summary": "Attach supporting evidence and highlight the most relevant source snippets.",
            "did": mapping.get("Evidence Agent", "Retrieve and rank evidence"),
            "concluded": "Top sources have been mapped to impacted categories",
            "why": [
                "Grounded outputs require source attribution",
                "Evidence ranking improves prioritization quality",
            ],
            "inputs": ["retrieved evidence"],
            "outputs": ["source map", "document digest"],
            "transcript": [
                {
                    "speaker": "Evidence Agent",
                    "message": "Aligned each blocker and recommendation with top supporting sources.",
                },
                {
                    "speaker": "Evidence Agent",
                    "message": "Forwarding citation map and snippets to Output Composer.",
                },
            ],
        },
        {
            "name": "Output Composer",
            "status": "done",
            "duration_ms": 24,
            "persona": "Executive brief writer",
            "background": "Decision support synthesis",
            "summary": "Assemble the final command-center view and exportable artifacts.",
            "did": mapping.get("Output Composer", "Generate prioritized next actions"),
            "concluded": priorities[0] if priorities else "Outputs assembled for handoff",
            "why": [
                "Top priorities are selected from weakest categories first",
                "Exports package the same reasoning for different audiences",
            ],
            "inputs": ["readiness", "risk", "evidence"],
            "outputs": ["dashboard sections", "exports"],
            "transcript": [
                {
                    "speaker": "Output Composer",
                    "message": "Merged readiness, risk, and evidence into stakeholder-friendly outputs.",
                },
                {
                    "speaker": "Output Composer",
                    "message": "Publishing dashboard sections and export artifacts.",
                },
            ],
        },
    ]
    return {"steps": steps}


def build_ui_sections(
    *,
    intake: dict[str, str],
    readiness: dict[str, int],
    blockers: list[Blocker],
    next_actions: list[str],
    evidence: list[EvidenceMatch],
    confidence: int,
    config: dict[str, Any],
    backend_mode: str,
    thinking: dict[str, Any],
) -> dict[str, Any]:
    avg = average_score(readiness)
    gauge = {
        "value": avg,
        "label": _readiness_label(avg),
        "color": _score_status(avg),
    }

    stakeholders = stakeholders_agent(intake, readiness)
    timeline = timeline_agent(readiness)
    documents = evidence_mapping_agent(evidence, config["scoring"]["categories"])
    agent_flow = agent_flow_agent(thinking)

    overview_blockers = [
        {
            "category": blocker.category,
            "severity": blocker.severity,
            "message": blocker.message,
        }
        for blocker in blockers
    ]

    return {
        "overview": {
            "gauge": gauge,
            "confidence": confidence,
            "backend_mode": backend_mode,
            "readiness": readiness,
            "blockers": overview_blockers,
            "recommendations": next_actions[:4],
            "quick_evidence": [doc["source"] for doc in documents["documents"][:3]],
        },
        "stakeholders": stakeholders,
        "timeline": timeline,
        "documents": documents,
        "thinking": thinking,
        "agent_flow": agent_flow,
        "actions": {
            "items": [
                "Generate Executive Brief",
                "Generate Engineering Checklist",
                "Export POC Plan",
            ]
        },
    }


def run_darla(
    customer_ask: str,
    groundtruth_root: Path,
    settings: DarlaSettings | None = None,
) -> DarlaResult:
    config = load_darla_config(groundtruth_root / "config")
    runtime_settings = settings or load_settings()
    backend = get_backend(runtime_settings)

    intake = intake_agent(customer_ask)
    evidence = retrieve_evidence(
        intake["raw"],
        load_groundtruth_documents(groundtruth_root / "data"),
        config["retrieval"],
    )
    if len(evidence) < int(config["policies"]["minimum_evidence_matches"]):
        raise RuntimeError(
            "Darla could not find enough approved ground-truth evidence for this ask."
        )

    readiness, readiness_feedback = readiness_insight_agent(intake, evidence, config)
    blockers = risk_agent(readiness)
    next_actions = next_actions_agent(readiness, config)
    confidence = confidence_agent(readiness, evidence, config["policies"])
    thinking = thinking_layer_agent(
        intake,
        readiness,
        blockers,
        evidence,
        next_actions,
        readiness_feedback,
    )

    backend_result = backend.generate_answer(
        query=intake["raw"],
        objective=intake["objective"],
        evidence=evidence,
        readiness=readiness,
        blockers=blockers,
        next_actions=next_actions,
        require_citations=bool(config["policies"].get("require_citations", True)),
    )
    confidence += int(backend_result.get("confidence_adjustment", 0))
    confidence = max(0, min(99, confidence))
    ui_sections = build_ui_sections(
      intake=intake,
      readiness=readiness,
      blockers=blockers,
      next_actions=next_actions,
      evidence=evidence,
      confidence=confidence,
      config=config,
      backend_mode=str(backend_result.get("mode", backend.name)),
            thinking=thinking,
    )

    return DarlaResult(
        project=config["app"]["name"],
        subtitle=config["app"]["subtitle"],
        timestamp_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        customer_ask=intake["raw"],
        objective=intake["objective"],
        readiness=readiness,
        blockers=blockers,
        evidence=evidence,
        next_actions=next_actions,
        confidence=confidence,
        policies=config["policies"],
        backend_mode=str(backend_result.get("mode", backend.name)),
        backend_model=str(backend_result.get("backend_model", "unknown")),
        answer=str(backend_result.get("answer", "")),
        citations=[str(item) for item in backend_result.get("citations", [])],
        verified=bool(backend_result.get("verified", False)),
        source_attribution=list(backend_result.get("source_attribution", [])),
        confidence_breakdown=dict(backend_result.get("confidence_breakdown", {})),
        ui_sections=ui_sections,
    )


def render_markdown(result: DarlaResult) -> str:
    lines = [
        f"# {result.project}",
        "",
        result.subtitle,
        "",
        f"Generated: {result.timestamp_utc}",
        "",
        "## Objective",
        result.objective,
        "",
        f"## Overall readiness: {average_score(result.readiness)}/100",
        f"Confidence: {result.confidence}/100",
        f"Backend mode: {result.backend_mode}",
        f"Backend model: {result.backend_model}",
        f"Verified: {'yes' if result.verified else 'no'}",
        "",
        "## Answer",
        result.answer,
        "",
        "## Scorecard",
    ]
    for category, score in result.readiness.items():
        lines.append(f"- {category}: {score}/100")

    lines.extend(["", "## Blockers"])
    if result.blockers:
        for blocker in result.blockers:
            lines.append(f"- {blocker.category} ({blocker.severity}): {blocker.message}")
    else:
        lines.append("- No major blockers detected")

    lines.extend(["", "## Evidence"])
    for match in result.evidence:
        lines.append(f"- {match.source} (score {match.score})")
        for snippet in match.snippets:
            lines.append(f"  - {snippet}")

    lines.extend(["", "## Next Actions"])
    for action in result.next_actions:
        lines.append(f"- {action}")

    lines.extend(["", "## Citations"])
    if result.citations:
        for citation in result.citations:
            lines.append(f"- {citation}")
    else:
        lines.append("- None")

    lines.extend(["", "## Confidence Breakdown"])
    if result.confidence_breakdown:
        for key, value in result.confidence_breakdown.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- None")

    lines.extend(["", "## Source Attribution"])
    if result.source_attribution:
        for item in result.source_attribution:
            lines.append(
                "- "
                f"{item.get('source', 'unknown')} "
                f"(score={item.get('score', 0)}, snippets={item.get('snippet_count', 0)})"
            )
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def render_html(result: DarlaResult) -> str:
    readiness_cards = "".join(
        f"""
        <div class=\"metric-card\">
          <span class=\"metric-label\">{category}</span>
          <strong class=\"metric-value\">{score}</strong>
        </div>
        """
        for category, score in result.readiness.items()
    )
    blockers = "".join(
        f"<li><span class=\"severity {blocker.severity}\">{blocker.severity.upper()}</span>{blocker.category}: {blocker.message}</li>"
        for blocker in result.blockers
    ) or "<li><span class=\"severity ok\">CLEAR</span>No major blockers detected.</li>"
    evidence = "".join(
        f"""
        <article class=\"evidence-card\">
          <h3>{match.source}</h3>
          <p class=\"evidence-score\">Evidence score: {match.score}</p>
          <ul>{''.join(f'<li>{snippet}</li>' for snippet in match.snippets)}</ul>
        </article>
        """
        for match in result.evidence
    )
    actions = "".join(f"<li>{action}</li>" for action in result.next_actions)
    citations = "".join(f"<li>{citation}</li>" for citation in result.citations) or "<li>None</li>"
    confidence_breakdown = "".join(
        f"<li>{key}: {value}</li>" for key, value in result.confidence_breakdown.items()
    ) or "<li>None</li>"
    source_attribution = "".join(
        "<li>"
        f"{item.get('source', 'unknown')} "
        f"(score={item.get('score', 0)}, snippets={item.get('snippet_count', 0)})"
        "</li>"
        for item in result.source_attribution
    ) or "<li>None</li>"

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{result.project} Command Center</title>
  <style>
    :root {{
      --bg: #09111f;
      --panel: rgba(10, 22, 38, 0.82);
      --panel-border: rgba(114, 167, 255, 0.18);
      --text: #eef4ff;
      --muted: #9ab0cf;
      --accent: #3ad0ff;
      --accent-2: #78f0b3;
      --warn: #ffbf5f;
      --danger: #ff6d6d;
      --grid: rgba(121, 170, 255, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "Segoe UI", "IBM Plex Sans", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(58, 208, 255, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(120, 240, 179, 0.12), transparent 24%),
        linear-gradient(180deg, #08101a 0%, #0a1322 45%, #09111f 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(var(--grid) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid) 1px, transparent 1px);
      background-size: 32px 32px;
      pointer-events: none;
      opacity: 0.45;
    }}
    .shell {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px;
      position: relative;
      z-index: 1;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 24px;
      backdrop-filter: blur(16px);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }}
    .hero {{ padding: 28px; margin-bottom: 24px; }}
    .eyebrow {{
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 12px;
      margin-bottom: 10px;
    }}
    h1 {{ margin: 0; font-size: 48px; line-height: 1; }}
    .subtitle {{ color: var(--muted); font-size: 18px; margin-top: 10px; }}
    .hero-grid, .content-grid {{
      display: grid;
      gap: 24px;
    }}
    .hero-grid {{ grid-template-columns: 1.25fr 0.75fr; margin-top: 24px; }}
    .content-grid {{ grid-template-columns: 1fr 1fr; }}
    .panel {{ padding: 24px; }}
    .panel h2 {{ margin-top: 0; font-size: 22px; }}
    .muted {{ color: var(--muted); }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    .metric-card {{
      border: 1px solid rgba(122, 172, 255, 0.18);
      border-radius: 18px;
      padding: 16px;
      background: rgba(5, 14, 25, 0.55);
    }}
    .metric-label {{ display: block; color: var(--muted); font-size: 14px; margin-bottom: 8px; }}
    .metric-value {{ font-size: 34px; color: var(--accent-2); }}
    .score-ring {{
      width: 180px;
      height: 180px;
      border-radius: 50%;
      margin: 8px auto 0;
      display: grid;
      place-items: center;
      background: conic-gradient(var(--accent) {average_score(result.readiness) * 3.6}deg, rgba(255,255,255,0.08) 0deg);
    }}
    .score-ring > div {{
      width: 136px;
      height: 136px;
      border-radius: 50%;
      background: #08111d;
      display: grid;
      place-items: center;
      text-align: center;
    }}
    ul {{ margin: 0; padding-left: 20px; }}
    li + li {{ margin-top: 10px; }}
    .severity {{
      display: inline-block;
      min-width: 62px;
      text-align: center;
      margin-right: 10px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.05em;
    }}
    .severity.high {{ background: rgba(255, 109, 109, 0.16); color: var(--danger); }}
    .severity.medium {{ background: rgba(255, 191, 95, 0.16); color: var(--warn); }}
    .severity.ok {{ background: rgba(120, 240, 179, 0.16); color: var(--accent-2); }}
    .evidence-card {{
      border: 1px solid rgba(122, 172, 255, 0.18);
      background: rgba(5, 14, 25, 0.55);
      border-radius: 18px;
      padding: 16px;
    }}
    .evidence-card + .evidence-card {{ margin-top: 14px; }}
    .evidence-card h3 {{ margin: 0 0 8px; }}
    .evidence-score {{ color: var(--accent); margin: 0 0 12px; }}
    @media (max-width: 960px) {{
      .hero-grid, .content-grid {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, 1fr); }}
      h1 {{ font-size: 38px; }}
    }}
    @media (max-width: 640px) {{
      .shell {{ padding: 18px; }}
      .metrics {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <section class=\"hero\">
      <div class=\"eyebrow\">GroundTruth Mission Control</div>
      <h1>{result.project}</h1>
      <p class=\"subtitle\">{result.subtitle}</p>
      <div class=\"hero-grid\">
        <div>
          <div class=\"panel\">
            <h2>Customer Ask</h2>
            <p class=\"muted\">{result.customer_ask}</p>
            <h2>Objective</h2>
            <p>{result.objective}</p>
            <p class=\"muted\">Generated {result.timestamp_utc}</p>
          </div>
        </div>
        <div class=\"panel\">
          <h2>Readiness Pulse</h2>
          <div class=\"score-ring\"><div><strong style=\"font-size:40px;\">{average_score(result.readiness)}</strong><span class=\"muted\">Overall score</span></div></div>
          <p class=\"muted\" style=\"text-align:center; margin-top:16px;\">Confidence {result.confidence}/100</p>
          <p class=\"muted\" style=\"text-align:center;\">Backend: {result.backend_mode} ({result.backend_model})</p>
        </div>
      </div>
    </section>
    <section class=\"content-grid\">
      <section class=\"panel\">
        <h2>Readiness Scorecard</h2>
        <div class=\"metrics\">{readiness_cards}</div>
      </section>
      <section class="panel">
        <h2>Confidence Breakdown</h2>
        <ul>{confidence_breakdown}</ul>
      </section>
      <section class="panel">
        <h2>Source Attribution</h2>
        <ul>{source_attribution}</ul>
      </section>
      <section class=\"panel\">
        <h2>Blockers</h2>
        <ul>{blockers}</ul>
      </section>
      <section class=\"panel\">
        <h2>Generated Answer</h2>
        <p>{result.answer}</p>
      </section>
      <section class=\"panel\">
        <h2>Evidence Rail</h2>
        {evidence}
      </section>
      <section class=\"panel\">
        <h2>Next Actions</h2>
        <ul>{actions}</ul>
      </section>
      <section class=\"panel\">
        <h2>Citations</h2>
        <ul>{citations}</ul>
      </section>
    </section>
  </main>
</body>
</html>
"""


def write_outputs(result: DarlaResult, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"darla_{stamp}"

    json_path = output_dir / f"{base_name}.json"
    md_path = output_dir / f"{base_name}.md"
    html_path = output_dir / f"{base_name}.html"

    json_payload = json.dumps(result.to_dict(), indent=2)
    markdown_payload = render_markdown(result)
    html_payload = render_html(result)

    json_path.write_text(json_payload + "\n", encoding="utf-8")
    md_path.write_text(markdown_payload, encoding="utf-8")
    html_path.write_text(html_payload, encoding="utf-8")

    latest_files = {
        "json": output_dir / "darla_latest.json",
        "markdown": output_dir / "darla_latest.md",
        "html": output_dir / "darla_latest.html",
    }
    latest_files["json"].write_text(json_payload + "\n", encoding="utf-8")
    latest_files["markdown"].write_text(markdown_payload, encoding="utf-8")
    latest_files["html"].write_text(html_payload, encoding="utf-8")

    return {
        "json": json_path,
        "markdown": md_path,
        "html": html_path,
        **latest_files,
    }
