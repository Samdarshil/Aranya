"""
Core structured-output schemas for Aranya.

Design decision (see docs/ARCHITECTURE.md, section "Decision Engine"):
raw LLM prose is NEVER the application's decision representation.
Every agent that produces a farmer-facing conclusion returns a
Recommendation built from these types, with evidence and provenance
attached. This module is intentionally dependency-free (stdlib only)
so the domain model does not require FastAPI/Pydantic to be installed
to be tested or reused by background workers.

A thin Pydantic mirror of these types lives at the API boundary
(backend/api/schemas_api.py) for request/response validation only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EvidenceSource(str, Enum):
    """Distinguishes *how* a piece of evidence was obtained.

    This distinction is required by spec section 14 (Explainability):
    the system must separate observed facts, model predictions, AI
    reasoning, farmer-provided information, and external data.
    """

    OBSERVED_SENSOR = "observed_sensor"          # e.g. a soil moisture probe reading
    VISION_MODEL = "vision_model"                # output of a CV/ML pipeline
    EXTERNAL_PROVIDER = "external_provider"      # weather/market/scheme API
    FARMER_REPORTED = "farmer_reported"          # farmer said so in conversation
    FARM_MEMORY = "farm_memory"                  # retrieved from historical records
    LLM_REASONING = "llm_reasoning"               # the orchestrator's own inference


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class Urgency(str, Enum):
    NONE = "none"
    MONITOR = "monitor"
    SOON = "soon"                 # act within days
    IMMEDIATE = "immediate"       # act within hours


@dataclass(frozen=True)
class Evidence:
    """A single, attributable fact backing a recommendation."""

    description: str
    source: EvidenceSource
    confidence: float  # 0.0-1.0; caller must justify anything > 0.9
    raw_value: Any | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")


@dataclass(frozen=True)
class Recommendation:
    """The structured output every agent must produce for a farmer-facing
    conclusion. See spec section 13 (Decision Engine) and section 14
    (Explainability) — every field here maps directly to one of the
    explainability questions the system must be able to answer.
    """

    problem: str                       # "What happened?"
    evidence: tuple[Evidence, ...]      # "What evidence supports this?"
    confidence: float                  # "How confident is Aranya?" (0.0-1.0, aggregate)
    severity: Severity
    urgency: Urgency
    recommended_action: str            # "What should I do?"
    reasoning: str                     # why this action follows from the evidence
    alternatives: tuple[str, ...] = ()
    monitoring_plan: str | None = None
    escalate_to_expert: bool = False
    escalation_reason: str | None = None
    source_agent: str = "unknown"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if not self.evidence:
            raise ValueError(
                "Recommendation created with no evidence — spec section 15 "
                "(Uncertainty & Safety) requires rejecting insufficient evidence "
                "rather than presenting an unsupported conclusion."
            )
        if self.escalate_to_expert and not self.escalation_reason:
            raise ValueError("escalate_to_expert=True requires escalation_reason")

    def requires_confirmation(self) -> bool:
        """Consequential recommendations require explicit farmer confirmation
        before any downstream action is taken (spec section 15:
        Assist -> Explain -> Confirm -> Act -> Monitor)."""
        return self.severity in (Severity.HIGH, Severity.CRITICAL) or self.urgency in (
            Urgency.SOON,
            Urgency.IMMEDIATE,
        )

    def as_farmer_summary(self) -> dict[str, Any]:
        """Flattened view matching the explainability questions in spec
        section 14, suitable for direct rendering in the UI or TTS."""
        return {
            "what_happened": self.problem,
            "why_it_matters": self.reasoning,
            "evidence": [e.description for e in self.evidence],
            "what_to_do": self.recommended_action,
            "how_urgent": self.urgency.value,
            "confidence_pct": round(self.confidence * 100),
            "ask_an_expert": self.escalate_to_expert,
            "escalation_reason": self.escalation_reason,
        }


_SEVERITY_RANK = {Severity.INFO: 0, Severity.LOW: 1, Severity.MODERATE: 2,
                   Severity.HIGH: 3, Severity.CRITICAL: 4}
_URGENCY_RANK = {Urgency.NONE: 0, Urgency.MONITOR: 1, Urgency.SOON: 2, Urgency.IMMEDIATE: 3}


@dataclass(frozen=True)
class GuardianAlert:
    """Farm Guardian's output — spec section 12. Wraps a Recommendation
    with the subject identity and priority ranking needed to decide what
    to surface to the farmer and in what order, without re-deriving that
    from the Recommendation's severity/urgency strings every time."""

    subject_type: str          # 'field' | 'animal' | 'farm'
    subject_ref: str           # human-readable, e.g. "FIELD-01"
    alert_type: str            # e.g. 'crop_health', 'livestock_health', 'weather'
    recommendation: Recommendation
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: datetime | None = None

    @property
    def priority(self) -> int:
        """Higher = more urgent. Used to sort a farmer's alert feed so
        the most actionable thing is always on top (spec section 12:
        alerts must be prioritized)."""
        return (_SEVERITY_RANK[self.recommendation.severity] * 10
                + _URGENCY_RANK[self.recommendation.urgency])

