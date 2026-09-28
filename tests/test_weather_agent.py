"""
Weather Agent tests — run with real threshold logic against a fake
in-memory provider (no network dependency, since this sandbox has none).
The fake provider satisfies the same WeatherProvider protocol the real
OpenWeatherMapProvider does, so these tests exercise the actual
WeatherAgent code path, not a mock of it.

Run with: python3 tests/test_weather_agent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.base import AgentContext, AgentError
from backend.agents.weather_agent import WeatherAgent
from backend.core.providers import ProviderUnavailable, WeatherReading
from backend.core.schemas import Severity, Urgency
from backend.memory.store import FarmMemory


@dataclass
class FakeWeatherProvider:
    """Conforms to backend.core.providers.WeatherProvider without any
    network call — returns a canned reading so tests are deterministic."""
    name: str = "fake_provider"
    canned_reading: WeatherReading | None = None
    should_fail: bool = False

    def get_current(self, lat: float, lng: float) -> WeatherReading:
        return self.get_forecast(lat, lng)

    def get_forecast(self, lat: float, lng: float, hours_ahead: int = 24) -> WeatherReading:
        if self.should_fail or self.canned_reading is None:
            raise ProviderUnavailable("fake provider has no data for this test case")
        return self.canned_reading


def _reading(**overrides) -> WeatherReading:
    defaults = dict(
        observed_at=datetime.now(timezone.utc),
        temperature_c=28.0,
        humidity_pct=60.0,
        rainfall_last_24h_mm=0.0,
        rainfall_forecast_24h_mm=0.0,
        wind_speed_kmh=10.0,
        provider="fake_provider",
        is_forecast=True,
    )
    defaults.update(overrides)
    return WeatherReading(**defaults)


class TestWeatherAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")
        self.context = AgentContext(farm_id=self.farm_id, memory=self.memory)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_provider_configured_raises_instead_of_fabricating(self):
        agent = WeatherAgent(provider=None)
        with self.assertRaises(AgentError) as ctx:
            agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertIn("No weather provider is configured", str(ctx.exception))

    def test_provider_failure_surfaces_as_retryable_agent_error(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(should_fail=True))
        with self.assertRaises(AgentError) as ctx:
            agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertTrue(ctx.exception.retryable)

    def test_routine_conditions_produce_info_severity(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(canned_reading=_reading()))
        rec = agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertEqual(rec.urgency, Urgency.NONE)

    def test_heavy_rain_forecast_triggers_moderate_recommendation(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(
            canned_reading=_reading(rainfall_forecast_24h_mm=60.0)
        ))
        rec = agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertEqual(rec.severity, Severity.MODERATE)
        self.assertEqual(rec.urgency, Urgency.SOON)
        self.assertIn("rain", rec.problem.lower())
        self.assertIn("drainage", rec.recommended_action.lower())

    def test_heat_stress_triggers_moderate_recommendation(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(
            canned_reading=_reading(temperature_c=42.0)
        ))
        rec = agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertEqual(rec.severity, Severity.MODERATE)
        self.assertIn("heat", rec.problem.lower())

    def test_multiple_triggers_report_most_severe_and_note_others(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(
            canned_reading=_reading(rainfall_forecast_24h_mm=60.0, wind_speed_kmh=55.0)
        ))
        rec = agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        self.assertIn("rain", rec.problem.lower())
        self.assertIn("wind", rec.problem.lower())  # noted as "also: ..."

    def test_weather_check_is_logged_to_farm_timeline(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(canned_reading=_reading()))
        agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        timeline = self.memory.get_farm_timeline(self.farm_id)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["event_type"], "weather_check")

    def test_every_evidence_item_is_attributed_to_external_provider(self):
        agent = WeatherAgent(provider=FakeWeatherProvider(canned_reading=_reading()))
        rec = agent.assess_conditions(self.context, lat=19.07, lng=72.87)
        for ev in rec.evidence:
            self.assertEqual(ev.source.value, "external_provider")


if __name__ == "__main__":
    unittest.main(verbosity=2)
