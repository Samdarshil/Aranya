"""
Soil Agent — spec sections 8, 20.

Fully deterministic: compares a SoilTest reading (pH, N, P, K) against
generic per-crop reference ranges (backend/core/soil_config.py) and
produces a Recommendation. No LLM call.

Confidence is scaled by the reading's source: a real lab report is
trusted more than a farmer's rough estimate of their own soil, which is
trusted more than nothing. This is an explicit modelling choice per spec
section 14 (distinguish observed facts from farmer-provided information)
— a farmer-reported pH of "acidic, I think" should not carry the same
weight as a lab result of 5.4.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency
from backend.core.soil_config import get_profile

_SOURCE_CONFIDENCE = {
    "lab_report": 0.9,
    "provider_api": 0.75,
    "farmer_reported": 0.5,
}
_SOURCE_TO_EVIDENCE = {
    "lab_report": EvidenceSource.OBSERVED_SENSOR,
    "provider_api": EvidenceSource.EXTERNAL_PROVIDER,
    "farmer_reported": EvidenceSource.FARMER_REPORTED,
}


class SoilAgent(Agent):
    name = "soil_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.evaluate_soil_test(context, **kwargs)

    def evaluate_soil_test(self, context: AgentContext, field_ref: str, crop_name: str,
                            ph: float | None, nitrogen_ppm: float | None,
                            phosphorus_ppm: float | None, potassium_ppm: float | None,
                            source: str = "farmer_reported") -> Recommendation:
        if source not in _SOURCE_CONFIDENCE:
            raise AgentError(f"Unknown soil data source {source!r}; expected one of "
                              f"{list(_SOURCE_CONFIDENCE)}", retryable=False)
        if all(v is None for v in (ph, nitrogen_ppm, phosphorus_ppm, potassium_ppm)):
            raise AgentError("No soil measurements provided — nothing to evaluate.", retryable=True)

        field_id = context.memory.get_or_create_field(context.farm_id, field_ref, crop_name)
        context.memory.save_soil_test(
            field_id=field_id, ph=ph, nitrogen_ppm=nitrogen_ppm,
            phosphorus_ppm=phosphorus_ppm, potassium_ppm=potassium_ppm, source=source,
        )

        profile = get_profile(crop_name)
        confidence = _SOURCE_CONFIDENCE[source]
        ev_source = _SOURCE_TO_EVIDENCE[source]

        evidence: list[Evidence] = []
        findings: list[str] = []
        actions: list[str] = []

        if ph is not None:
            evidence.append(Evidence(f"Soil pH: {ph} (source: {source})", ev_source, confidence, raw_value=ph))
            if ph < profile.ph_min:
                findings.append(f"soil is more acidic than {crop_name} tolerates well "
                                 f"(pH {ph} vs recommended {profile.ph_min}-{profile.ph_max})")
                actions.append("Apply agricultural lime to raise soil pH gradually; re-test after 2-3 months.")
            elif ph > profile.ph_max:
                findings.append(f"soil is more alkaline than {crop_name} tolerates well "
                                 f"(pH {ph} vs recommended {profile.ph_min}-{profile.ph_max})")
                actions.append("Apply elemental sulfur or an acidifying organic amendment; re-test after 2-3 months.")

        nutrient_checks = [
            ("nitrogen", nitrogen_ppm, profile.nitrogen_low_ppm, profile.nitrogen_high_ppm, "nitrogen-rich fertilizer (e.g. urea) in split doses"),
            ("phosphorus", phosphorus_ppm, profile.phosphorus_low_ppm, profile.phosphorus_high_ppm, "phosphate fertilizer (e.g. DAP/SSP) at planting"),
            ("potassium", potassium_ppm, profile.potassium_low_ppm, profile.potassium_high_ppm, "potash fertilizer (e.g. MOP)"),
        ]
        for label, value, low, high, remedy in nutrient_checks:
            if value is None:
                continue
            evidence.append(Evidence(f"Soil {label}: {value} ppm (source: {source})", ev_source, confidence, raw_value=value))
            if value < low:
                findings.append(f"{label} is low ({value} ppm, below {low} ppm)")
                actions.append(f"Apply {remedy}.")
            elif value > high:
                findings.append(f"{label} is already high ({value} ppm, above {high} ppm) — "
                                 f"further {label} fertilizer is unlikely to help and may cause runoff pollution")

        if not findings:
            return Recommendation(
                problem=f"Soil conditions for field {field_ref} are within the typical range for {crop_name}",
                evidence=tuple(evidence),
                confidence=confidence,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="No soil amendment needed based on this test.",
                reasoning=f"pH and available N/P/K all fall within generic reference ranges for {crop_name} "
                          "(see docs/STATUS.md for the caveat on these being generic, not region-calibrated).",
                source_agent=self.name,
            )

        severity = Severity.MODERATE if len(findings) > 1 or source != "farmer_reported" else Severity.LOW
        return Recommendation(
            problem=f"Soil issues detected for field {field_ref}: {'; '.join(findings)}",
            evidence=tuple(evidence),
            confidence=confidence,
            severity=severity,
            urgency=Urgency.MONITOR,
            recommended_action=" ".join(actions) if actions else "Monitor and consider a lab soil test to confirm.",
            reasoning=f"Compared against generic reference ranges for {crop_name}. "
                      + ("A lab-reported test is reasonably trustworthy." if source == "lab_report"
                         else "This reading is farmer-reported, not lab-verified — treat the specific "
                              "numbers as approximate and consider a lab test before investing in inputs."),
            monitoring_plan="Re-test soil after applying any amendment (2-3 months) to confirm it worked.",
            escalate_to_expert=(source == "farmer_reported" and len(findings) > 1),
            escalation_reason=("Multiple soil issues reported without lab verification — an agricultural "
                                "extension officer can confirm before you spend on inputs."
                                if (source == "farmer_reported" and len(findings) > 1) else None),
            source_agent=self.name,
        )
