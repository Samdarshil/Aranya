"""
Farm Guardian tests — spec section 12: alerts must be relevant,
non-spammy, and prioritized. These are exercised through the
Orchestrator (not GuardianAgent in isolation) because the dedup logic
depends on what's already in Farm Memory, which is exactly the
integration point worth testing.

Run with: python3 tests/test_guardian.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from backend.agents.orchestrator import Orchestrator
from backend.core.providers import ProviderUnavailable, WeatherReading
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


@dataclass
class FakeWeatherProvider:
    name: str = "fake_provider"
    canned_reading: WeatherReading | None = None

    def get_current(self, lat, lng):
        return self.get_forecast(lat, lng)

    def get_forecast(self, lat, lng, hours_ahead: int = 24):
        if self.canned_reading is None:
            raise ProviderUnavailable("no data configured for this test")
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


class TestFarmGuardian(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "test.db"
        self.memory = FarmMemory(db_path=db_path)
        self.orchestrator = Orchestrator.default(
            memory=self.memory, weather_provider=FakeWeatherProvider(canned_reading=_reading())
        )
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _crop_bgr(self, name: str):
        return pil_to_bgr(Image.open(SAMPLES / "crop" / f"{name}.jpg"))

    def test_high_severity_crop_scan_creates_an_alert(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-01", "Tomato", is_demo=True)
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["subject_ref"], "FIELD-01")
        self.assertEqual(alerts[0]["alert_type"], "crop_health")

    def test_healthy_scan_does_not_create_an_alert(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_healthy"),
                                            "FIELD-02", "Tomato", is_demo=True)
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        self.assertEqual(len(alerts), 0)

    def test_repeated_identical_severe_scan_does_not_spam(self):
        # Same field, same severe photo, scanned twice — should only ever
        # produce ONE active alert, not one per scan.
        for _ in range(3):
            self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                                "FIELD-03", "Tomato", is_demo=True)
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        field_alerts = [a for a in alerts if a["subject_ref"] == "FIELD-03"]
        self.assertEqual(len(field_alerts), 1, "identical repeated risk must not spam multiple alerts")

    def test_worsening_condition_creates_a_new_alert(self):
        # moderate -> severe on the same field IS a meaningful change and
        # should re-alert, even though both are above threshold.
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_moderate"),
                                            "FIELD-04", "Tomato", is_demo=True)
        # moderate alone doesn't cross threshold (LOW severity) - confirm no alert yet
        alerts_after_moderate = self.orchestrator.get_active_alerts(self.farm_id)
        self.assertEqual(len([a for a in alerts_after_moderate if a["subject_ref"] == "FIELD-04"]), 0)

        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-04", "Tomato", is_demo=True)
        alerts_after_severe = self.orchestrator.get_active_alerts(self.farm_id)
        field_alerts = [a for a in alerts_after_severe if a["subject_ref"] == "FIELD-04"]
        self.assertEqual(len(field_alerts), 1)
        self.assertEqual(field_alerts[0]["severity"], "high")

    def test_weather_alert_and_crop_alert_are_prioritized_correctly(self):
        # Crop HIGH severity should outrank a weather MODERATE alert.
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-05", "Tomato", is_demo=True)
        heavy_rain_orchestrator = Orchestrator.default(
            memory=self.memory,
            weather_provider=FakeWeatherProvider(canned_reading=_reading(rainfall_forecast_24h_mm=60.0)),
        )
        heavy_rain_orchestrator.handle_weather_check(self.farm_id, lat=19.07, lng=72.87)

        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        self.assertEqual(len(alerts), 2)
        self.assertEqual(alerts[0]["alert_type"], "crop_health")  # higher priority, listed first
        self.assertEqual(alerts[1]["alert_type"], "weather")

    def test_acknowledging_an_alert_removes_it_from_active_feed(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-06", "Tomato", is_demo=True)
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        self.assertEqual(len(alerts), 1)
        self.orchestrator.acknowledge_alert(self.farm_id, alerts[0]["id"])
        self.assertEqual(len(self.orchestrator.get_active_alerts(self.farm_id)), 0)

    def test_acknowledging_another_farms_alert_raises(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-09", "Tomato", is_demo=True)
        alert_id = self.orchestrator.get_active_alerts(self.farm_id)[0]["id"]

        other_farmer_id = self.memory.get_or_create_farmer("Other Farmer", phone="+91-other-guardian")
        other_farm_id = self.memory.get_or_create_farm(other_farmer_id, "Other Farm")
        with self.assertRaises(ValueError):
            self.orchestrator.acknowledge_alert(other_farm_id, alert_id)
        # And it must still be active for the real owner afterward.
        self.assertEqual(len(self.orchestrator.get_active_alerts(self.farm_id)), 1)

    def test_acknowledging_nonexistent_alert_raises(self):
        with self.assertRaises(ValueError):
            self.orchestrator.acknowledge_alert(self.farm_id, 999999)


if __name__ == "__main__":
    unittest.main(verbosity=2)
