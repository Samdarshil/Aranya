"""
Farm Guardian — spec section 12.

Farm State (a Recommendation another agent just produced)
    + Historical Context (the last alert issued for this same subject)
    -> Risk Evaluation (does severity/urgency cross the alert threshold?)
    -> Meaningful Change Detection (is this different from what was
       already alerted?)
    -> Alert Decision (save a GuardianAlert, or stay quiet)

This is intentionally NOT a scheduler or a background job runner — no
such infrastructure exists in this environment. It is the decision
function a scheduler would call: given a fresh Recommendation, decide
whether it should become a farmer-facing alert. Wiring a real cron/queue
around `GuardianAgent.consider()` is the remaining piece (see
docs/STATUS.md) — this class already contains the actual logic, which is
the part spec section 12 cares about (relevant, non-spammy,
prioritized), not the scheduling mechanism.

Fully deterministic — no LLM call.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext
from backend.core.schemas import GuardianAlert, Recommendation, Severity, Urgency

# Only these severities/urgencies are worth interrupting a farmer for.
# Anything below this (INFO/LOW severity with NONE/MONITOR urgency) is
# still saved as a Recommendation and visible in history, but does not
# become an alert — spec section 12: alerts must be non-spammy.
ALERT_SEVERITY_FLOOR = Severity.MODERATE
ALERT_URGENCY_FLOOR = Urgency.SOON

_SEVERITY_ORDER = [Severity.INFO, Severity.LOW, Severity.MODERATE, Severity.HIGH, Severity.CRITICAL]
_URGENCY_ORDER = [Urgency.NONE, Urgency.MONITOR, Urgency.SOON, Urgency.IMMEDIATE]


class GuardianAgent(Agent):
    name = "guardian_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        # Guardian doesn't produce its own Recommendation — it evaluates
        # ones other agents already made. Present for Agent-contract
        # consistency; real callers use `consider()` directly.
        raise NotImplementedError(
            "GuardianAgent has no standalone run() — call consider() with "
            "a Recommendation another agent produced."
        )

    def consider(self, context: AgentContext, recommendation: Recommendation,
                 recommendation_id: int | None, subject_type: str, subject_id: int,
                 subject_ref: str, alert_type: str) -> GuardianAlert | None:
        """Returns a GuardianAlert if this recommendation should interrupt
        the farmer, or None if it's below threshold or a repeat of an
        already-alerted state for this subject."""

        if not self._crosses_threshold(recommendation):
            return None

        last_alert = context.memory.get_latest_alert_for_subject(
            context.farm_id, subject_type, subject_id
        )
        if last_alert is not None and not self._is_meaningful_change(last_alert, recommendation):
            return None

        alert = GuardianAlert(
            subject_type=subject_type,
            subject_ref=subject_ref,
            alert_type=alert_type,
            recommendation=recommendation,
        )
        context.memory.save_guardian_alert(
            farm_id=context.farm_id, subject_type=subject_type, subject_id=subject_id,
            subject_ref=subject_ref, alert_type=alert_type,
            severity=recommendation.severity.value, urgency=recommendation.urgency.value,
            priority=alert.priority, problem=recommendation.problem,
            recommendation_id=recommendation_id,
        )
        return alert

    @staticmethod
    def _crosses_threshold(rec: Recommendation) -> bool:
        return (
            _SEVERITY_ORDER.index(rec.severity) >= _SEVERITY_ORDER.index(ALERT_SEVERITY_FLOOR)
            or _URGENCY_ORDER.index(rec.urgency) >= _URGENCY_ORDER.index(ALERT_URGENCY_FLOOR)
        )

    @staticmethod
    def _is_meaningful_change(last_alert: dict, rec: Recommendation) -> bool:
        """A change is meaningful if severity or urgency moved, or the
        problem description itself changed (e.g. a different deviation
        was detected even at the same severity). An identical repeat of
        the same problem at the same severity/urgency is NOT alerted
        again — that's the spam case spec section 12 explicitly warns
        against."""
        return (
            last_alert["severity"] != rec.severity.value
            or last_alert["urgency"] != rec.urgency.value
            or last_alert["problem"] != rec.problem
        )
