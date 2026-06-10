"""CPU-friendly deterministic backend for local practice mode."""

from __future__ import annotations

from typing import Any

from groundtruth.agents.backends.base import BaseBackend


class PracticeBackend(BaseBackend):
    """Deterministic practice backend that does not require GPU or external APIs."""

    name = "practice"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

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
        citations = [match.source for match in evidence]
        evidence_preview = []
        source_attribution = []
        for match in evidence:
            if match.snippets:
                evidence_preview.append(f"[{match.source}] {match.snippets[0]}")
            source_attribution.append(
                {
                    "source": match.source,
                    "score": int(match.score),
                    "snippet_count": len(match.snippets),
                    "top_snippet": match.snippets[0] if match.snippets else "",
                }
            )

        average_readiness = int(sum(readiness.values()) / max(1, len(readiness)))
        total_evidence_score = sum(match.score for match in evidence)
        blocker_penalty = min(len(blockers) * 3, 9)
        evidence_strength_bonus = min(total_evidence_score // 2, 8)
        confidence_adjustment = max(-12, min(8, evidence_strength_bonus - blocker_penalty))

        lowest_categories = sorted(readiness.items(), key=lambda item: item[1])[:2]
        strongest_sources = sorted(
            source_attribution,
            key=lambda item: (item["score"], item["snippet_count"]),
            reverse=True,
        )[:2]

        answer_lines = [
            "Darla practice-mode response (deterministic):",
            f"Objective: {objective}",
            (
                "Readiness summary: "
                + ", ".join(
                    f"{category}={score}" for category, score in readiness.items()
                )
            ),
        ]
        if blockers:
            answer_lines.append(
                "Blockers: "
                + ", ".join(
                    f"{blocker.category} ({blocker.severity})" for blocker in blockers
                )
            )
        else:
            answer_lines.append("Blockers: none")

        if lowest_categories:
            answer_lines.append(
                "Lowest readiness categories: "
                + ", ".join(f"{name}={score}" for name, score in lowest_categories)
            )

        if evidence_preview:
            answer_lines.append("Ground-truth evidence:")
            answer_lines.extend(f"- {line}" for line in evidence_preview)
        else:
            answer_lines.append("Ground-truth evidence: none")

        if strongest_sources:
            answer_lines.append("Top sources:")
            answer_lines.extend(
                f"- {item['source']} (score={item['score']}, snippets={item['snippet_count']})"
                for item in strongest_sources
            )

        answer_lines.append("Recommended next actions:")
        answer_lines.extend(f"- {action}" for action in next_actions[:3])

        return {
            "answer": "\n".join(answer_lines),
            "citations": citations if require_citations else [],
            "verified": bool(evidence),
            "backend_model": self.model_name,
            "mode": self.name,
            "source_attribution": source_attribution,
            "confidence_adjustment": confidence_adjustment,
            "confidence_breakdown": {
                "average_readiness": average_readiness,
                "total_evidence_score": total_evidence_score,
                "evidence_strength_bonus": evidence_strength_bonus,
                "blocker_penalty": blocker_penalty,
                "confidence_adjustment": confidence_adjustment,
            },
        }
