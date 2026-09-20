"""
API-boundary request/response models.

Deliberately separate from backend/core/schemas.py (the domain model).
The domain model (Recommendation, Evidence, ...) is stdlib dataclasses so
it has zero dependencies and can be unit-tested and reused by background
workers without pulling in FastAPI/Pydantic. This module is the only
place Pydantic is used, and only for validating what crosses the HTTP
boundary. NOTE: requires `pydantic` and `fastapi` installed — not
available in the sandbox this was authored in (no network access to
`pip install`), so this file is written-but-unexecuted; see
docs/STATUS.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceOut(BaseModel):
    description: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0)


class RecommendationOut(BaseModel):
    problem: str
    evidence: list[EvidenceOut]
    confidence: float = Field(ge=0.0, le=1.0)
    severity: str
    urgency: str
    recommended_action: str
    reasoning: str
    alternatives: list[str] = []
    monitoring_plan: str | None = None
    escalate_to_expert: bool
    escalation_reason: str | None = None
    source_agent: str
    generated_at: datetime

    @classmethod
    def from_domain(cls, rec) -> "RecommendationOut":
        return cls(
            problem=rec.problem,
            evidence=[EvidenceOut(description=e.description, source=e.source.value,
                                   confidence=e.confidence) for e in rec.evidence],
            confidence=rec.confidence,
            severity=rec.severity.value,
            urgency=rec.urgency.value,
            recommended_action=rec.recommended_action,
            reasoning=rec.reasoning,
            alternatives=list(rec.alternatives),
            monitoring_plan=rec.monitoring_plan,
            escalate_to_expert=rec.escalate_to_expert,
            escalation_reason=rec.escalation_reason,
            source_agent=rec.source_agent,
            generated_at=rec.generated_at,
        )


class FieldHistoryOut(BaseModel):
    field_ref: str
    scan_count: int
    latest_status: str | None = None
    latest_affected_area_pct: float | None = None
    latest_timestamp: str | None = None
    message: str | None = None
