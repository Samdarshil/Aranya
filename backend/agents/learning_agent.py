"""
Learning Agent — spec section 8.

Fully deterministic bookkeeping + simple statistics — not a model that
retrains itself (that would need real ML infrastructure this codebase
doesn't have; see docs/STATUS.md). What it actually does:

  1. Records outcomes: did the farmer follow a given recommendation, and
     what happened afterward (improved / no change / worsened)? This is
     the TreatmentOutcome entity from spec section 9 (modelled in
     models_sqlalchemy.py, never wired to anything until now).
  2. Computes an honest track record per source agent: what fraction of
     farmers who FOLLOWED that agent's advice reported improvement.

Deliberately NOT claimed as causal or scientifically controlled — this
is observational data from farmers who chose to follow advice (probably
correlated with other factors), not a randomized trial. The track record
says so explicitly, every time, and refuses to report a percentage at
all below a minimum sample size rather than implying confidence a
handful of data points doesn't support (spec section 15).
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError

VALID_OUTCOMES = ("improved", "no_change", "worsened")
MIN_SAMPLE_SIZE = 5


class LearningAgent(Agent):
    name = "learning_agent"

    def run(self, context: AgentContext, **kwargs) -> None:
        raise NotImplementedError(
            "LearningAgent has no standalone run() — call record_outcome() "
            "or get_track_record() directly."
        )

    def record_outcome(self, context: AgentContext, recommendation_id: int | None,
                        source_agent: str, followed_advice: bool, outcome: str,
                        notes: str | None = None) -> int:
        if outcome not in VALID_OUTCOMES:
            raise AgentError(
                f"Invalid outcome {outcome!r}; expected one of {VALID_OUTCOMES}.",
                retryable=False,
            )
        return context.memory.record_outcome(
            farm_id=context.farm_id, recommendation_id=recommendation_id,
            source_agent=source_agent, followed_advice=followed_advice,
            outcome=outcome, notes=notes,
        )

    def get_track_record(self, context: AgentContext, source_agent: str) -> dict:
        """Returns a dict, not a Recommendation — this is meta-information
        about the system's own performance, not farm-specific advice, so
        forcing it into the Recommendation schema (which assumes a farm
        subject and an action to take) would be a poor fit."""
        outcomes = context.memory.get_outcomes_for_agent(source_agent)
        followed = [o for o in outcomes if o["followed_advice"]]

        if len(followed) < MIN_SAMPLE_SIZE:
            return {
                "source_agent": source_agent,
                "total_outcomes_recorded": len(outcomes),
                "followed_count": len(followed),
                "sufficient_data": False,
                "message": f"Only {len(followed)} outcome(s) recorded where advice was "
                           f"followed — need at least {MIN_SAMPLE_SIZE} before reporting "
                           f"a track record.",
            }

        improved = sum(1 for o in followed if o["outcome"] == "improved")
        worsened = sum(1 for o in followed if o["outcome"] == "worsened")
        no_change = len(followed) - improved - worsened
        improvement_rate = improved / len(followed) * 100

        not_followed = [o for o in outcomes if not o["followed_advice"]]

        return {
            "source_agent": source_agent,
            "total_outcomes_recorded": len(outcomes),
            "followed_count": len(followed),
            "sufficient_data": True,
            "improved_pct": round(improvement_rate, 1),
            "no_change_pct": round(no_change / len(followed) * 100, 1),
            "worsened_pct": round(worsened / len(followed) * 100, 1),
            "not_followed_count": len(not_followed),
            "caveat": "This is observational, not a controlled comparison — farmers who "
                      "chose to follow advice may differ in other ways from those who "
                      "didn't (e.g. more attentive, better resourced). Treat this as a "
                      "rough signal, not proof the advice caused the outcome.",
        }
