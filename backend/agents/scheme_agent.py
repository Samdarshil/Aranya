"""
Scheme Agent — spec section 8.

Fully deterministic: matches the farmer's stated land size and category
against SchemeCriteria.matches() (backend/core/scheme_config.py). No LLM
call, no external provider call — unlike Weather/Market, scheme
*structures* don't change day-to-day, so this doesn't need the same
"no provider configured" honesty pattern. What it DOES need, and does,
is an explicit staleness/completeness caveat on every recommendation
(spec section 15): the underlying data is a curated snapshot, not a live
government feed, and is very likely incomplete (state-specific schemes
aren't represented at all) and possibly outdated. This agent is upfront
about that in every single Recommendation it produces, not just in a
docstring.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.scheme_config import SCHEMES
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency


class SchemeAgent(Agent):
    name = "scheme_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.match_schemes(context, **kwargs)

    def match_schemes(self, context: AgentContext, land_acres: float | None = None,
                       category: str | None = None, crop_name: str | None = None) -> Recommendation:
        if land_acres is None and category is None:
            raise AgentError(
                "Need at least a land size or a farmer category to check scheme eligibility.",
                retryable=True,
            )

        matched = [s for s in SCHEMES if s.matches(land_acres, category)]

        evidence = [
            Evidence(
                description=f"Checked against {len(SCHEMES)} schemes in Aranya's reference list "
                            f"(land: {land_acres if land_acres is not None else 'not given'} acres, "
                            f"category: {category or 'not given'})",
                source=EvidenceSource.FARMER_REPORTED, confidence=1.0,
            ),
        ]
        for s in matched:
            evidence.append(Evidence(
                description=f"{s.name}: {s.benefit_summary}",
                source=EvidenceSource.FARM_MEMORY, confidence=0.5,  # see reasoning caveat below
            ))

        context.memory.log_event(
            context.farm_id, "scheme_check",
            f"Matched {len(matched)} scheme(s) for land={land_acres}, category={category}",
        )

        staleness_caveat = (
            "This is checked against a small, curated reference list, not a live government feed — "
            "it is very likely incomplete (state-specific schemes aren't included at all) and the "
            "listed amounts/eligibility may be outdated. Confirm at your local agriculture office or "
            "the scheme's official portal before relying on this."
        )

        if not matched:
            return Recommendation(
                problem="No schemes in Aranya's reference list matched what you provided",
                evidence=tuple(evidence),
                confidence=0.3,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="Visit your local agriculture department office — they maintain the "
                                    "full current list including state-specific schemes this list doesn't cover.",
                reasoning=staleness_caveat,
                source_agent=self.name,
            )

        action_lines = [f"{s.name}: apply via {s.apply_via}." for s in matched]
        return Recommendation(
            problem=f"{len(matched)} scheme(s) may apply to you based on what you provided",
            evidence=tuple(evidence),
            confidence=0.4,  # deliberately capped — see reasoning
            severity=Severity.INFO,
            urgency=Urgency.NONE,
            recommended_action=" ".join(action_lines),
            reasoning=staleness_caveat,
            monitoring_plan="Scheme rules and cutoff dates change — re-check before each cropping season.",
            source_agent=self.name,
        )
