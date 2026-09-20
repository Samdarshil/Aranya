"""
Weather Agent — spec sections 8, 20.

Fully deterministic: thresholds over a WeatherReading, no LLM call. The
one rule this agent enforces strictly (spec section 3): if no
WeatherProvider is configured or the provider raises ProviderUnavailable,
this agent raises AgentError — it never invents a plausible-looking
temperature or rainfall figure to keep the UI populated.

Thresholds below are conservative defaults for general crop conditions,
not crop-specific agronomy — see docs/STATUS.md for what a real
implementation would need (per-crop heat/rain tolerance tables).
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.providers import ProviderUnavailable, WeatherProvider, WeatherReading
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency

HEAVY_RAIN_FORECAST_MM = 40.0
HEAT_STRESS_TEMP_C = 40.0
HIGH_WIND_KMH = 50.0


class WeatherAgent(Agent):
    name = "weather_agent"

    def __init__(self, provider: WeatherProvider | None):
        # provider may be None (no API key configured) — that's a valid,
        # honest state, not an error at construction time. It only
        # becomes an error when someone actually asks for a reading.
        self._provider = provider

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        lat = kwargs["lat"]
        lng = kwargs["lng"]
        return self.assess_conditions(context, lat, lng)

    def assess_conditions(self, context: AgentContext, lat: float, lng: float) -> Recommendation:
        if self._provider is None:
            raise AgentError(
                "No weather provider is configured (WEATHER_API_KEY unset). "
                "Weather-based recommendations are unavailable until a provider "
                "is connected — no reading has been fabricated.",
                retryable=False,
            )
        try:
            reading = self._provider.get_forecast(lat, lng, hours_ahead=24)
        except ProviderUnavailable as exc:
            raise AgentError(f"Weather provider unavailable: {exc}", retryable=True) from exc

        rec = self._build_recommendation(reading)

        context.memory.log_event(
            context.farm_id, "weather_check",
            f"{rec.problem} (source: {reading.provider})",
        )
        return rec

    @staticmethod
    def _build_recommendation(reading: WeatherReading) -> Recommendation:
        evidence = [
            Evidence(
                description=f"Forecast rainfall next 24h: {reading.rainfall_forecast_24h_mm:.0f}mm",
                source=EvidenceSource.EXTERNAL_PROVIDER, confidence=0.7,
                raw_value=reading.rainfall_forecast_24h_mm,
            ),
            Evidence(
                description=f"Forecast temperature: {reading.temperature_c:.1f}\u00b0C",
                source=EvidenceSource.EXTERNAL_PROVIDER, confidence=0.7,
                raw_value=reading.temperature_c,
            ),
            Evidence(
                description=f"Forecast wind speed: {reading.wind_speed_kmh:.0f} km/h",
                source=EvidenceSource.EXTERNAL_PROVIDER, confidence=0.7,
                raw_value=reading.wind_speed_kmh,
            ),
        ]

        triggers: list[tuple[str, str, Severity, Urgency]] = []
        if reading.rainfall_forecast_24h_mm >= HEAVY_RAIN_FORECAST_MM:
            triggers.append((
                "Heavy rain expected in the next 24 hours",
                "Delay any planned irrigation, ensure field drainage channels are clear, "
                "and hold off on any pesticide/fertilizer application that rain would wash away.",
                Severity.MODERATE, Urgency.SOON,
            ))
        if reading.temperature_c >= HEAT_STRESS_TEMP_C:
            triggers.append((
                "Extreme heat expected",
                "Irrigate during cooler hours (early morning/evening), provide shade for "
                "livestock, and watch for heat-stress symptoms in animals.",
                Severity.MODERATE, Urgency.SOON,
            ))
        if reading.wind_speed_kmh >= HIGH_WIND_KMH:
            triggers.append((
                "High winds expected",
                "Secure loose structures/covers and delay spraying operations — "
                "wind drift will reduce treatment effectiveness and waste product.",
                Severity.LOW, Urgency.MONITOR,
            ))

        if not triggers:
            return Recommendation(
                problem="No significant weather risk in the next 24 hours",
                evidence=tuple(evidence),
                confidence=0.7,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="No weather-driven action needed today.",
                reasoning=f"All forecast values are within routine ranges "
                          f"(source: {reading.provider}).",
                source_agent=WeatherAgent.name,
            )

        # Multiple simultaneous triggers: report the most severe, list the rest as context.
        triggers.sort(key=lambda t: (t[2].value, t[3].value), reverse=True)
        top_problem, top_action, top_severity, top_urgency = triggers[0]
        other_notes = [t[0] for t in triggers[1:]]

        return Recommendation(
            problem=top_problem + (f" (also: {', '.join(other_notes)})" if other_notes else ""),
            evidence=tuple(evidence),
            confidence=0.7,
            severity=top_severity,
            urgency=top_urgency,
            recommended_action=top_action,
            reasoning=f"Forecast values crossed a routine risk threshold "
                      f"(source: {reading.provider}, which is a third-party forecast, "
                      f"not a guarantee).",
            monitoring_plan="Re-check the forecast before making irrigation or spraying decisions.",
            source_agent=WeatherAgent.name,
        )
