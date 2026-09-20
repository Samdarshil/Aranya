"""
Vision Agent — spec sections 8, 11, 34.

Wraps the classical CV pipelines (backend/vision/crop_analyzer.py,
backend/vision/livestock_analyzer.py) and is responsible for the parts
those modules deliberately don't do themselves:

  1. Turning a CropAnalysisResult / LivestockAnalysisResult into Evidence +
     a structured Recommendation (spec section 13: raw pipeline output is
     not the app's decision representation).
  2. Retrieving the subject's history from Farm Memory *before* analysis
     (for livestock, the baseline the pipeline compares against) and
     writing the new observation back afterwards (spec section 9).
  3. Applying the uncertainty/safety rules from spec section 15: low
     leaf-segmentation quality means low confidence, not a confident
     "Healthy" verdict; skin-patch detections always escalate to a vet
     rather than naming a disease the pipeline cannot actually identify.

No LLM call happens in this agent — it is fully deterministic, per spec
section 8's guidance to prefer a deterministic service over an LLM agent
where one suffices.
"""

from __future__ import annotations

import numpy as np

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.image_validation import ImageValidationError, validate_image
from backend.core.schemas import (
    Evidence,
    EvidenceSource,
    Recommendation,
    Severity,
    Urgency,
)
from backend.vision.crop_analyzer import analyze_crop_image
from backend.vision.livestock_analyzer import analyze_livestock_image

MIN_LEAF_AREA_PCT_FOR_CONFIDENT_READ = 8.0  # below this, segmentation is too poor to trust


class VisionAgent(Agent):
    name = "vision_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        """Dispatches to analyze_crop or analyze_livestock based on
        kwargs["kind"]. Direct callers (the orchestrator) call
        analyze_crop/analyze_livestock directly; this exists to satisfy
        the Agent base contract for any future generic agent-runner."""
        kind = kwargs.pop("kind", None)
        if kind == "crop":
            return self.analyze_crop(context, **kwargs)
        if kind == "livestock":
            return self.analyze_livestock(context, **kwargs)
        raise AgentError(f"VisionAgent.run: unknown kind {kind!r}, expected 'crop' or 'livestock'")

    # -- Crop -----------------------------------------------------------------
    def analyze_crop(self, context: AgentContext, bgr: np.ndarray, field_ref: str,
                      crop_name: str, is_demo: bool = False) -> Recommendation:
        try:
            validate_image(bgr)
        except ImageValidationError as exc:
            raise AgentError(str(exc), retryable=True) from exc

        result = analyze_crop_image(bgr, crop_name)

        if result.leaf_area_pct_of_frame < MIN_LEAF_AREA_PCT_FOR_CONFIDENT_READ:
            raise AgentError(
                f"Only {result.leaf_area_pct_of_frame}% of the frame was identified as "
                "plant matter — too little to screen reliably. Ask for a closer, "
                "well-lit photo filling most of the frame.",
                retryable=True,
            )

        field_id = context.memory.get_or_create_field(context.farm_id, field_ref, crop_name)
        scan_id = context.memory.save_vision_scan(
            subject_type="field", subject_id=field_id, kind="crop",
            status=result.status, score=result.affected_area_pct,
            confidence=result.heuristic_confidence / 100.0,
            raw_metrics=result.raw_metrics, is_demo=is_demo,
        )

        evidence = (
            Evidence(
                description=f"{result.affected_area_pct}% of the visible leaf area shows "
                            "abnormal colour or lesion patterns",
                source=EvidenceSource.VISION_MODEL,
                confidence=result.heuristic_confidence / 100.0,
                raw_value=result.raw_metrics,
            ),
            *[
                Evidence(
                    description=ind.detail,
                    source=EvidenceSource.VISION_MODEL,
                    confidence=result.heuristic_confidence / 100.0,
                )
                for ind in result.indicators
                if ind.detected
            ],
        )

        severity, urgency, escalate, escalation_reason = self._crop_severity(result.status)

        rec = Recommendation(
            problem=result.condition_summary,
            evidence=evidence,
            confidence=result.heuristic_confidence / 100.0,
            severity=severity,
            urgency=urgency,
            recommended_action=result.recommendation,
            reasoning=(
                "Classical computer-vision screening (colour deviation, lesion "
                "detection, texture irregularity) — not a trained disease "
                "classifier — flagged the indicators listed above as evidence."
            ),
            monitoring_plan=f"Re-scan field {field_ref} in 3-5 days to track whether "
                             "the affected area is growing or shrinking.",
            escalate_to_expert=escalate,
            escalation_reason=escalation_reason,
            source_agent=self.name,
        )

        context.memory.save_recommendation(
            scan_id=scan_id, farm_id=context.farm_id, problem=rec.problem,
            severity=rec.severity.value, urgency=rec.urgency.value,
            confidence=rec.confidence, recommended_action=rec.recommended_action,
            reasoning=rec.reasoning, evidence=[e.description for e in rec.evidence],
            source_agent=rec.source_agent, escalate_to_expert=rec.escalate_to_expert,
            escalation_reason=rec.escalation_reason,
        )
        context.memory.log_event(
            context.farm_id, "crop_scan",
            f"Scanned field {field_ref} ({crop_name}): {result.status} "
            f"({result.affected_area_pct}% affected)",
        )
        return rec

    @staticmethod
    def _crop_severity(status: str) -> tuple[Severity, Urgency, bool, str | None]:
        if status == "Healthy":
            return Severity.INFO, Urgency.NONE, False, None
        if status == "At Risk":
            return Severity.LOW, Urgency.MONITOR, False, None
        return (
            Severity.HIGH,
            Urgency.SOON,
            True,
            "Significant abnormal-area indicators — the CV pipeline can flag a "
            "pattern but cannot confirm a specific pathogen; an agricultural "
            "extension officer should verify before treatment.",
        )

    # -- Livestock --------------------------------------------------------
    def analyze_livestock(self, context: AgentContext, bgr: np.ndarray, animal_ref: str,
                           species: str, frames_for_motion: list[np.ndarray] | None = None,
                           is_demo: bool = False) -> Recommendation:
        try:
            validate_image(bgr)
        except ImageValidationError as exc:
            raise AgentError(str(exc), retryable=True) from exc

        animal_id = context.memory.get_or_create_animal(context.farm_id, animal_ref, species)
        baseline = context.memory.get_animal_baseline(animal_id)

        result = analyze_livestock_image(
            bgr, animal_ref, species, baseline=baseline, frames_for_motion=frames_for_motion,
        )

        scan_id = context.memory.save_vision_scan(
            subject_type="animal", subject_id=animal_id, kind="livestock",
            status=result.risk_level, score=result.risk_score,
            confidence=0.6,  # pipeline doesn't emit a calibrated confidence; see docs/STATUS.md
            raw_metrics=result.raw_metrics, is_demo=is_demo,
        )

        evidence = tuple(
            Evidence(description=d, source=EvidenceSource.VISION_MODEL, confidence=0.6)
            for d in result.deviations
        ) or (
            Evidence(
                description="No notable deviations detected in this observation",
                source=EvidenceSource.VISION_MODEL, confidence=0.6,
            ),
        )
        if baseline is not None:
            evidence = evidence + (
                Evidence(
                    description=f"Compared against this animal's own history "
                                f"({len(context.memory.get_animal_history(animal_id))} prior observations)",
                    source=EvidenceSource.FARM_MEMORY, confidence=1.0,
                ),
            )

        severity, urgency, escalate, escalation_reason = self._livestock_severity(
            result.risk_level, result.biomarkers.skin_patch_count > 0
        )

        rec = Recommendation(
            problem=f"{result.risk_level} for {animal_ref} ({species})",
            evidence=evidence,
            confidence=0.6,
            severity=severity,
            urgency=urgency,
            recommended_action=result.recommendation,
            reasoning=(
                "Rule-based scoring over coat colour/texture and (if a video was "
                "provided) movement biomarkers, compared against this animal's own "
                "prior observations where available. This is a screening pattern, "
                "not a veterinary diagnosis."
            ),
            monitoring_plan=f"Re-observe {animal_ref} in the next few days to confirm the trend.",
            escalate_to_expert=escalate,
            escalation_reason=escalation_reason,
            source_agent=self.name,
        )

        context.memory.save_recommendation(
            scan_id=scan_id, farm_id=context.farm_id, problem=rec.problem,
            severity=rec.severity.value, urgency=rec.urgency.value,
            confidence=rec.confidence, recommended_action=rec.recommended_action,
            reasoning=rec.reasoning, evidence=[e.description for e in rec.evidence],
            source_agent=rec.source_agent, escalate_to_expert=rec.escalate_to_expert,
            escalation_reason=rec.escalation_reason,
        )
        context.memory.log_event(
            context.farm_id, "livestock_observation",
            f"Observed {animal_ref} ({species}): {result.risk_level} (score {result.risk_score})",
        )
        return rec

    @staticmethod
    def _livestock_severity(risk_level: str, has_skin_patch: bool) -> tuple[Severity, Urgency, bool, str | None]:
        if has_skin_patch:
            return (
                Severity.MODERATE, Urgency.SOON, True,
                "A localised skin/coat patch was detected. This pipeline can localise "
                "the anomaly but cannot distinguish lumpy skin disease, ringworm/mange, "
                "dermatitis, parasites, or a simple wound from a photo alone — a "
                "veterinarian should examine it in person.",
            )
        mapping = {
            "Low Risk": (Severity.INFO, Urgency.NONE, False, None),
            "Moderate Risk": (Severity.LOW, Urgency.MONITOR, False, None),
            "Elevated Risk": (Severity.MODERATE, Urgency.SOON, False, None),
            "High Risk": (
                Severity.HIGH, Urgency.SOON, True,
                "Multiple deviations from this animal's baseline were detected — "
                "recommend a veterinary examination to confirm.",
            ),
        }
        return mapping.get(risk_level, (Severity.LOW, Urgency.MONITOR, False, None))
