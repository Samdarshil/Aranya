"""
Planning Agent tests — run with: python3 tests/test_planning_agent.py

These specifically test COMPOSITION: that PlanningAgent reads what
SoilAgent already wrote to Farm Memory, calls WeatherAgent live, and
degrades gracefully when either input is missing, rather than testing
each concern in isolation (that's what test_soil_agent.py and
test_weather_agent.py already cover).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.orchestrator import Orchestrator
from backend.core.providers import ProviderUnavailable, WeatherReading
from backend.core.schemas import Severity
from backend.memory.store import FarmMemory


@dataclass
class FakeWeatherProvider:
    name: str = "fake_provider"
    canned_reading: WeatherReading | None = None

    def get_current(self, lat, lng):
        return self.get_forecast(lat, lng)

    def get_forecast(self, lat, lng, hours_ahead: int = 24):
        if self.canned_reading is None:
            raise ProviderUnavailable("no data configured")
        return self.canned_reading


def _reading(**overrides):
    import datetime as dt
    defaults = dict(
        observed_at=dt.datetime.now(dt.timezone.utc), temperature_c=28.0, humidity_pct=60.0,
        rainfall_last_24h_mm=0.0, rainfall_forecast_24h_mm=0.0, wind_speed_kmh=10.0,
        provider="fake_provider", is_forecast=True,
    )
    defaults.update(overrides)
    return WeatherReading(**defaults)


class TestPlanningAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_in_season_no_other_data_is_low_severity_with_a_soil_test_nudge(self):
        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-01", "Rice", current_month=6,  # Rice window is 6-7
        )
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("soil test", rec.recommended_action.lower())

    def test_out_of_season_recommends_waiting_and_names_the_window(self):
        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-02", "Wheat", current_month=6,  # Wheat window is 10-12
        )
        self.assertEqual(rec.severity, Severity.MODERATE)
        self.assertIn("wait", rec.recommended_action.lower())
        self.assertTrue(any("10" in e.description or "12" in e.description for e in rec.evidence))

    def test_reads_existing_soil_test_without_writing_a_new_one(self):
        # Pre-populate a soil test the way SoilAgent would have.
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-03", "Tomato")
        self.memory.save_soil_test(field_id=field_id, ph=4.5, nitrogen_ppm=40,
                                    phosphorus_ppm=30, potassium_ppm=200, source="lab_report")
        history_before = self.memory.get_soil_test_history(field_id)

        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-03", "Tomato", current_month=6,  # Tomato Kharif window
        )
        self.assertIn("soil conditions may not suit", rec.problem.lower())
        self.assertEqual(rec.severity, Severity.MODERATE)

        history_after = self.memory.get_soil_test_history(field_id)
        self.assertEqual(len(history_before), len(history_after),
                          "PlanningAgent must not write a new soil test just by reading one")

    def test_good_soil_and_in_season_recommends_proceeding(self):
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-04", "Tomato")
        self.memory.save_soil_test(field_id=field_id, ph=6.4, nitrogen_ppm=40,
                                    phosphorus_ppm=30, potassium_ppm=200, source="lab_report")
        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-04", "Tomato", current_month=6,
        )
        self.assertIn("looks ready", rec.problem.lower())
        self.assertEqual(rec.severity, Severity.INFO)

    def test_live_weather_risk_is_folded_into_the_recommendation(self):
        orchestrator = Orchestrator.default(
            memory=self.memory,
            weather_provider=FakeWeatherProvider(canned_reading=_reading(rainfall_forecast_24h_mm=60.0)),
        )
        rec = orchestrator.handle_planning_query(
            self.farm_id, "FIELD-05", "Rice", lat=19.07, lng=72.87, current_month=6,
        )
        self.assertTrue(any("weather" in e.description.lower() for e in rec.evidence))
        self.assertIn("weather", rec.problem.lower())

    def test_missing_weather_provider_degrades_gracefully_without_crashing(self):
        # No provider configured at all — must not raise, must still return a recommendation.
        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-06", "Rice", lat=19.07, lng=72.87, current_month=6,
        )
        self.assertIsNotNone(rec)
        self.assertTrue(any("unavailable" in e.description.lower() for e in rec.evidence))

    def test_crop_with_no_calendar_data_still_returns_a_recommendation(self):
        rec = self.orchestrator.handle_planning_query(
            self.farm_id, "FIELD-07", "Dragonfruit", current_month=6,
        )
        self.assertIsNotNone(rec)
        self.assertTrue(any("no sowing-season" in e.description.lower() for e in rec.evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
