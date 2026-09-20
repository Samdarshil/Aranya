"""
Expert Escalation Agent — spec section 8.

Every agent's Recommendation can already set `escalate_to_expert=True`
with an `escalation_reason` (spec sections 13-15) — VisionAgent does this
for high-severity crop findings and skin-patch livestock detections;
SoilAgent does it for multiple unverified farmer-reported findings. Until
now, that flag was purely informational: nothing tracked it, queued it,
or gave an expert a queue to work from. This agent closes that loop.

Fully deterministic — this is a bookkeeping/workflow agent, not a
judgement agent. It doesn't decide *whether* to escalate (the originating
agent already decided that); it decides how to record and prioritize the
escalation once one is needed.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext
from backend.core.schemas import Recommendation, Severity

_SEVERITY_RANK = {Severity.INFO: 0, Severity.LOW: 1, Severity.MODERATE: 2,
                   Severity.HIGH: 3, Severity.CRITICAL: 4}


class ExpertEscalationAgent(Agent):
    name = "expert_escalation_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        raise NotImplementedError(
            "ExpertEscalationAgent has no standalone run() — call "
            "escalate_if_needed() with a Recommendation another agent produced."
        )

    def escalate_if_needed(self, context: AgentContext, recommendation: Recommendation,
                            recommendation_id: int | None) -> int | None:
        """Creates a pending consultation request if `recommendation` was
        flagged for escalation, and returns its id — or None if no
        escalation was needed. Idempotency is the caller's (Orchestrator's)
        responsibility, same as Guardian — this agent doesn't itself
        check for duplicates, since "should this specific recommendation
        be escalated" was already decided once, not something to
        re-derive here."""
        if not recommendation.escalate_to_expert:
            return None
        return context.memory.create_consultation_request(
            farm_id=context.farm_id,
            recommendation_id=recommendation_id,
            source_agent=recommendation.source_agent,
            problem=recommendation.problem,
            escalation_reason=recommendation.escalation_reason or "No reason given.",
            severity=recommendation.severity.value,
        )

    def resolve(self, context: AgentContext, consultation_id: int,
                expert_name: str, notes: str) -> dict:
        """An expert responds to a pending consultation. Raises if the
        consultation doesn't exist or belongs to a different farm — an
        expert resolving farm A's consultation while looking at farm B's
        id would be a real data-integrity bug, not just an edge case."""
        consultation = context.memory.get_consultation(consultation_id)
        if consultation is None:
            raise ValueError(f"No consultation with id {consultation_id}")
        if consultation["farm_id"] != context.farm_id:
            raise ValueError(
                f"Consultation {consultation_id} belongs to a different farm."
            )
        context.memory.resolve_consultation(consultation_id, expert_name, notes)
        return {**consultation, "status": "resolved", "expert_name": expert_name,
                "resolution_notes": notes}

    @staticmethod
    def queue_priority(consultations: list[dict]) -> list[dict]:
        """Sorts a farmer's (or an expert's cross-farm) pending queue by
        severity, most urgent first — an expert working through a queue
        should see the highest-severity cases before low-severity ones,
        not just whatever came in most recently."""
        return sorted(
            consultations,
            key=lambda c: _SEVERITY_RANK.get(Severity(c["severity"]), 0),
            reverse=True,
        )
