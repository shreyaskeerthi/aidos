# Darla

Agentic customer readiness and execution cockpit

Generated: 2026-06-04T14:40:22+00:00

## Objective
Build a secure customer readiness RAG cockpit with citations and owner handoff.

## Overall readiness: 75/100
Confidence: 87/100
Backend mode: practice
Backend model: darla-practice-deterministic
Verified: yes

## Answer
Darla practice-mode response (deterministic):
Objective: Build a secure customer readiness RAG cockpit with citations and owner handoff.
Readiness summary: Business=91, Data=91, Security=69, Infrastructure=69, Ownership=91, Timeline=44
Blockers: Security (medium), Infrastructure (medium), Timeline (high)
Lowest readiness categories: Timeline=44, Security=69
Ground-truth evidence:
- [shi_customer_readiness.md] # SHI Customer Readiness Signals

SHI opportunity reviews are strongest when the team can point to a defined use case, an executive sponsor, named delivery ownership, and a measurable business KPI for the first pilot.
- [security_controls.md] # Secure Ground Truth Controls

Answers should be grounded in approved internal documents and should return citations for every material claim.
- [nvidia_stack_alignment.md] # NVIDIA Stack Alignment

NVIDIA RAG Blueprint deployments typically align around document ingestion, retrieval, reranking, and grounded answer generation.
Top sources:
- shi_customer_readiness.md (score=5, snippets=2)
- security_controls.md (score=4, snippets=2)
Recommended next actions:
- Build a two-week POC plan with milestones, blockers, and exit criteria.
- Set a review checkpoint for readiness after the first ingestion run.
- Complete a security review before scaling ingestion beyond the pilot corpus.

## Scorecard
- Business: 91/100
- Data: 91/100
- Security: 69/100
- Infrastructure: 69/100
- Ownership: 91/100
- Timeline: 44/100

## Blockers
- Security (medium): Security readiness is 69/100. Darla needs stronger proof before this can be presented as deployment-ready.
- Infrastructure (medium): Infrastructure readiness is 69/100. Darla needs stronger proof before this can be presented as deployment-ready.
- Timeline (high): Timeline readiness is 44/100. Darla needs stronger proof before this can be presented as deployment-ready.

## Evidence
- shi_customer_readiness.md (score 5)
  - # SHI Customer Readiness Signals

SHI opportunity reviews are strongest when the team can point to a defined use case, an executive sponsor, named delivery ownership, and a measurable business KPI for the first pilot.
  - Customer readiness improves when the engagement includes an agreed timeline, success criteria, and a clear path from discovery to proof of concept.
- security_controls.md (score 4)
  - # Secure Ground Truth Controls

Answers should be grounded in approved internal documents and should return citations for every material claim.
  - Internet access should remain disabled for sensitive customer workflows unless explicitly approved by policy.
- nvidia_stack_alignment.md (score 2)
  - # NVIDIA Stack Alignment

NVIDIA RAG Blueprint deployments typically align around document ingestion, retrieval, reranking, and grounded answer generation.
  - Agentic workflows can improve the demo story by breaking a vague request into readiness checks, evidence collection, and next-step outputs instead of returning a single chatbot answer.

## Next Actions
- Build a two-week POC plan with milestones, blockers, and exit criteria.
- Set a review checkpoint for readiness after the first ingestion run.
- Complete a security review before scaling ingestion beyond the pilot corpus.
- Lock approved sources and require evidence-backed answers in every demo flow.
- Choose the deployment target and reserve GPU capacity for the demo environment.
- Document model endpoints, vector store settings, and deployment dependencies.

## Citations
- shi_customer_readiness.md
- security_controls.md
- nvidia_stack_alignment.md

## Confidence Breakdown
- average_readiness: 75
- total_evidence_score: 11
- evidence_strength_bonus: 5
- blocker_penalty: 9
- confidence_adjustment: -4

## Source Attribution
- shi_customer_readiness.md (score=5, snippets=2)
- security_controls.md (score=4, snippets=2)
- nvidia_stack_alignment.md (score=2, snippets=2)
