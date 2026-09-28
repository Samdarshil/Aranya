"""
Research Agent — spec section 8.

Fully deterministic: keyword-overlap search over a curated knowledge
base (backend/core/knowledge_base.py). No LLM call, no embeddings, no
external API — verified to actually return sensible top matches for
real queries (see the module's own inline check during development).

This is explicitly a *reference lookup*, not a diagnosis — unlike
VisionAgent, which has actual photo evidence to reason from, this agent
only has the farmer's own text description, which is far weaker
evidence. Every recommendation says so and points back to the Vision
scan as the stronger option when a photo is available.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.knowledge_base import search
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency

MIN_MATCH_SCORE = 0.15


class ResearchAgent(Agent):
    name = "research_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.answer_question(context, **kwargs)

    def answer_question(self, context: AgentContext, query: str,
                         crop_name: str | None = None) -> Recommendation:
        if not query or not query.strip():
            raise AgentError("Need a question or description to search for.", retryable=True)

        results = search(query, crop_name=crop_name)
        results = [(e, s) for e, s in results if s >= MIN_MATCH_SCORE]

        context.memory.log_event(
            context.farm_id, "research_query",
            f"'{query[:80]}' -> {len(results)} match(es)",
        )

        if not results:
            return Recommendation(
                problem=f"No close match found in Aranya's reference material for: {query}",
                evidence=(Evidence(
                    description="Searched Aranya's curated knowledge base "
                                f"({'filtered to ' + crop_name if crop_name else 'all crops'}) "
                                "— no entry scored above the match threshold",
                    source=EvidenceSource.FARM_MEMORY, confidence=1.0,
                ),),
                confidence=0.2,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="Try describing what you see more specifically (color, pattern, "
                                    "which part of the plant), or use a crop photo scan if you have one — "
                                    "photo evidence is much stronger than a text description.",
                reasoning="This is a small, curated reference set, not a general search engine — "
                          "many real conditions won't be in it.",
                source_agent=self.name,
            )

        top_entry, top_score = results[0]
        evidence = [
            Evidence(
                description=f"Best match: {e.title} ({e.category}) — match strength {s:.0%}",
                source=EvidenceSource.FARM_MEMORY, confidence=min(s, 0.7),  # capped, see reasoning
            )
            for e, s in results
        ]

        symptoms_text = "; ".join(top_entry.symptoms)
        management_text = " ".join(f"{i+1}. {m}." for i, m in enumerate(top_entry.management))

        return Recommendation(
            problem=f"Closest match: {top_entry.title} — typical symptoms: {symptoms_text}",
            evidence=tuple(evidence),
            confidence=min(top_score, 0.6),  # a text-only keyword match is never high-confidence
            severity=Severity.INFO,
            urgency=Urgency.NONE,
            recommended_action=management_text,
            reasoning="This is a text-based reference lookup, not a diagnosis — there's no photo "
                      "evidence behind this match, only keyword overlap with your description. "
                      "If you have a photo, a crop scan gives much stronger evidence than this does.",
            escalate_to_expert=(top_entry.title == "Late blight"),  # the one KB entry explicitly noting urgency
            escalation_reason=("Late blight spreads fast and can destroy a crop within days — "
                                "worth a quick expert confirmation rather than waiting."
                                if top_entry.title == "Late blight" else None),
            source_agent=self.name,
        )
