"""
Planning Agent — spec section 8.

The first agent in this codebase that actively composes other agents'
outputs rather than acting alone:
  - reads the field's latest soil test from Farm Memory (written by
    SoilAgent) and checks it against the same per-crop profile SoilAgent
    uses, WITHOUT re-running SoilAgent (no side effect of writing a new
    soil test record just to ask "is this field ready to plant?");
  - optionally calls WeatherAgent live for a near-term risk check, and
    degrades gracefully (proceeds without a weather opinion, doesn't
    fail the whole recommendation) if no provider is configured — this
    mirrors WeatherAgent's own honesty rule, just one layer up;
  - checks the calendar month against generic sowing-season windows
    (backend/core/planning_config.py).

Fully deterministic — no LLM call. This is exactly the kind of
multi-signal synthesis spec section 7's pipeline describes
("Specialized Agents -> Evidence Collection -> Reasoning -> Decision
Engine"), done without an LLM because the reasoning here is a fixed,
explainable rule set, not open-ended judgement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.agents.base import Agent, AgentContext, AgentError
from backend.agents.weather_agent import WeatherAgent
from backend.core.planning_config import get_windows, nearest_window
from backend.core.providers import WeatherProvider
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency
from backend.core.soil_config import get_profile


class PlanningAgent(Agent):
    name = "planning_agent"

    def __init__(self, weather_provider: WeatherProvider | None = None):
        # Reuses WeatherAgent's own threshold logic rather than duplicating
        # it — if WeatherAgent's rain/heat thresholds change, Planning
        # automatically stays consistent with them.
        self._weather_agent = WeatherAgent(provider=weather_provider)

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.recommend_sowing_window(context, **kwargs)

    def recommend_sowing_window(self, context: AgentContext, field_ref: str, crop_name: str,
                                 lat: float | None = None, lng: float | None = None,
                                 current_month: int | None = None) -> Recommendation:
        month = current_month or datetime.now(timezone.utc).month
        windows = get_windows(crop_name)
        field_id = context.memory.get_or_create_field(context.farm_id, field_ref, crop_name)

        evidence: list[Evidence] = []
        concerns: list[str] = []
        actions: list[str] = []
        severity = Severity.INFO
        urgency = Urgency.NONE

        # -- Season check -----------------------------------------------------
        if windows is None:
            evidence.append(Evidence(
                f"No sowing-season reference data on file for {crop_name}",
                EvidenceSource.FARM_MEMORY, confidence=1.0,
            ))
            concerns.append(f"no seasonal calendar data available for {crop_name}")
        else:
            in_season = any(w.contains(month) for w in windows)
            best = nearest_window(crop_name, month)
            if in_season:
                evidence.append(Evidence(
                    f"Current month is within a typical sowing window for {crop_name} ({best.season_label})",
                    EvidenceSource.FARM_MEMORY, confidence=0.6,
                ))
            else:
                evidence.append(Evidence(
                    f"Current month is outside typical sowing windows for {crop_name}; "
                    f"nearest window is {best.season_label} (months {best.start_month}-{best.end_month})",
                    EvidenceSource.FARM_MEMORY, confidence=0.6,
                ))
                concerns.append(f"outside the typical {best.season_label} sowing window for {crop_name}")
                actions.append(f"Consider waiting for the {best.season_label} window "
                                f"(typically months {best.start_month}-{best.end_month}) for better establishment odds.")
                severity = Severity.MODERATE
                urgency = Urgency.MONITOR

        # -- Soil check (reads what SoilAgent already wrote, no side effect) --
        soil = context.memory.get_latest_soil_test(field_id)
        if soil is None:
            evidence.append(Evidence(
                "No soil test on file for this field", EvidenceSource.FARM_MEMORY, confidence=1.0,
            ))
            concerns.append("no soil test on file — soil suitability is unknown")
            actions.append("Consider a soil test before investing in this planting.")
        else:
            profile = get_profile(crop_name)
            soil_issues = []
            if soil["ph"] is not None and not (profile.ph_min <= soil["ph"] <= profile.ph_max):
                soil_issues.append(f"pH {soil['ph']} outside {profile.ph_min}-{profile.ph_max}")
            evidence.append(Evidence(
                f"Latest soil test (source: {soil['source']}, {soil['tested_at']}): "
                f"pH {soil['ph']}, N {soil['nitrogen_ppm']}ppm, P {soil['phosphorus_ppm']}ppm, "
                f"K {soil['potassium_ppm']}ppm",
                EvidenceSource.FARM_MEMORY, confidence=0.8,
            ))
            if soil_issues:
                concerns.append(f"soil conditions may not suit {crop_name}: {'; '.join(soil_issues)}")
                actions.append("Address the soil pH/nutrient issue (see the field's soil recommendation) before sowing.")
                severity = Severity.MODERATE

        # -- Weather check (optional, degrades gracefully) ---------------------
        if lat is not None and lng is not None:
            try:
                weather_rec = self._weather_agent.assess_conditions(context, lat, lng)
                evidence.append(Evidence(
                    f"Near-term weather: {weather_rec.problem}",
                    EvidenceSource.EXTERNAL_PROVIDER, confidence=0.7,
                ))
                if weather_rec.severity in (Severity.MODERATE, Severity.HIGH, Severity.CRITICAL):
                    concerns.append(f"near-term weather risk: {weather_rec.problem.lower()}")
                    actions.append("Hold off a few days if heavy rain or extreme heat is imminent — "
                                   "check the weather recommendation for specifics.")
            except AgentError:
                # No provider configured, or it failed — proceed without a
                # weather opinion rather than failing the whole planning
                # recommendation. This mirrors spec section 3: absence of
                # a data source is not itself an error for the caller.
                evidence.append(Evidence(
                    "Weather data unavailable for this check", EvidenceSource.EXTERNAL_PROVIDER, confidence=0.0,
                ))

        if not evidence:
            raise AgentError("No data available to base a planting recommendation on.", retryable=True)

        if not concerns:
            problem = f"Field {field_ref} looks ready for {crop_name} sowing"
            action = f"Proceed with sowing {crop_name} in field {field_ref}."
            reasoning = "Season timing, soil data (where available), and near-term weather (where checked) all look clear."
        else:
            problem = f"{len(concerns)} consideration(s) before sowing {crop_name} in field {field_ref}: " + "; ".join(concerns)
            action = " ".join(actions) if actions else "Review the concerns above before sowing."
            reasoning = "Combines the sowing-season calendar, this field's latest soil test (if any), " \
                        "and a live weather check (if location was provided)."

        return Recommendation(
            problem=problem,
            evidence=tuple(evidence),
            confidence=0.6,
            severity=severity,
            urgency=urgency,
            recommended_action=action,
            reasoning=reasoning,
            monitoring_plan="Re-check this recommendation if you delay sowing by more than a couple of weeks.",
            source_agent=self.name,
        )
