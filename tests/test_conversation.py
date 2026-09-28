"""
Conversational entry point tests — run with: python3 tests/test_conversation.py

Tests handle_farmer_message end-to-end: fake LLM produces an intent,
Orchestrator dispatches to the real (deterministic) agent, the real
agent reads/writes real Farm Memory. Only the classification step is
faked — everything downstream of it is the same code path the
structured API endpoints use.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.intent_router import IntentRouter
from backend.agents.orchestrator import Orchestrator
from backend.core.providers import ProviderUnavailable, WeatherReading
from backend.memory.store import FarmMemory


@dataclass
class FakeLLMProvider:
    name: str = "fake_llm"
    canned_response: str = ""

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.canned_response


@dataclass
class FakeWeatherProvider:
    name: str = "fake_weather"
    canned_reading: WeatherReading | None = None

    def get_current(self, lat, lng):
        return self.get_forecast(lat, lng)

    def get_forecast(self, lat, lng, hours_ahead: int = 24):
        if self.canned_reading is None:
            raise ProviderUnavailable("no data")
        return self.canned_reading


def _reading(**overrides):
    import datetime as dt
    defaults = dict(
        observed_at=dt.datetime.now(dt.timezone.utc), temperature_c=28.0, humidity_pct=60.0,
        rainfall_last_24h_mm=0.0, rainfall_forecast_24h_mm=0.0, wind_speed_kmh=10.0,
        provider="fake_weather", is_forecast=True,
    )
    defaults.update(overrides)
    return WeatherReading(**defaults)


class TestConversationalEntryPoint(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _orchestrator(self, llm_response: str, weather_reading=None) -> Orchestrator:
        return Orchestrator.default(
            memory=self.memory,
            weather_provider=FakeWeatherProvider(canned_reading=weather_reading),
            llm_provider=FakeLLMProvider(canned_response=llm_response),
        )

    def test_weather_question_routes_through_real_weather_agent(self):
        orch = self._orchestrator(
            '{"action": "weather_check", "params": {}, "clarification_needed": null}',
            weather_reading=_reading(rainfall_forecast_24h_mm=60.0),
        )
        result = orch.handle_farmer_message(self.farm_id, "will it rain today?", lat=19.07, lng=72.87)
        self.assertEqual(result["type"], "recommendation")
        self.assertIn("rain", result["what_happened"].lower())

    def test_weather_question_without_location_asks_for_it(self):
        orch = self._orchestrator('{"action": "weather_check", "params": {}, "clarification_needed": null}')
        result = orch.handle_farmer_message(self.farm_id, "will it rain today?")  # no lat/lng
        self.assertEqual(result["type"], "clarification")
        self.assertIn("location", result["message"].lower())

    def test_field_history_question_reads_real_farm_memory(self):
        # Pre-populate real history the way a crop scan would.
        orch = self._orchestrator("")
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-01", "Tomato")
        self.memory.save_vision_scan(subject_type="field", subject_id=field_id, kind="crop",
                                      status="At Risk", score=12.0, confidence=0.8, raw_metrics={})

        orch2 = self._orchestrator(
            '{"action": "field_history", "params": {"field_ref": "FIELD-01", "crop_name": "Tomato"}, '
            '"clarification_needed": null}'
        )
        result = orch2.handle_farmer_message(self.farm_id, "pichli baar FIELD-01 mein kya hua tha")
        self.assertEqual(result["type"], "history")
        self.assertEqual(result["scan_count"], 1)
        self.assertEqual(result["latest_status"], "At Risk")

    def test_planning_question_composes_soil_and_planning_agents(self):
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-02", "Tomato")
        self.memory.save_soil_test(field_id=field_id, ph=4.5, nitrogen_ppm=40,
                                    phosphorus_ppm=30, potassium_ppm=200, source="lab_report")
        orch = self._orchestrator(
            '{"action": "planning_query", "params": {"field_ref": "FIELD-02", "crop_name": "Tomato"}, '
            '"clarification_needed": null}'
        )
        result = orch.handle_farmer_message(self.farm_id, "should I plant tomatoes in FIELD-02")
        self.assertEqual(result["type"], "recommendation")
        self.assertIn("soil", result["what_happened"].lower())

    def test_ambiguous_message_asks_for_clarification_not_a_guess(self):
        orch = self._orchestrator(
            '{"action": "unclear", "params": {}, "clarification_needed": "Which field do you mean?"}'
        )
        result = orch.handle_farmer_message(self.farm_id, "check on it")
        self.assertEqual(result["type"], "clarification")
        self.assertEqual(result["message"], "Which field do you mean?")

    def test_no_llm_configured_fails_honestly(self):
        orch = Orchestrator.default(memory=self.memory)  # no llm_provider passed
        result = orch.handle_farmer_message(self.farm_id, "will it rain today?")
        self.assertEqual(result["type"], "error")
        self.assertIn("No LLM provider", result["message"])

    def test_scheme_question_via_chat(self):
        orch = self._orchestrator(
            '{"action": "scheme_match", "params": {"land_acres": "3", "category": "sc"}, '
            '"clarification_needed": null}'
        )
        result = orch.handle_farmer_message(self.farm_id, "what schemes can I get, I have 3 acres and I'm SC category")
        self.assertEqual(result["type"], "recommendation")
        self.assertIn("SMAM", result["what_to_do"])

    def test_research_question_via_chat(self):
        orch = self._orchestrator(
            '{"action": "research_query", "params": {"query": "white powdery coating on tomato leaves"}, '
            '"clarification_needed": null}'
        )
        result = orch.handle_farmer_message(self.farm_id, "my tomato leaves have a white powdery coating, what is it?")
        self.assertEqual(result["type"], "recommendation")
        self.assertIn("Powdery mildew", result["what_happened"])

    def test_garbled_llm_output_does_not_crash_the_whole_request(self):
        orch = self._orchestrator("completely garbled non-json output")
        result = orch.handle_farmer_message(self.farm_id, "something")
        self.assertEqual(result["type"], "clarification")


if __name__ == "__main__":
    unittest.main(verbosity=2)
