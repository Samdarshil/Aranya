"""
Soil Agent tests — run with: python3 tests/test_soil_agent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.orchestrator import Orchestrator
from backend.core.schemas import Severity
from backend.memory.store import FarmMemory


class TestSoilAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_ideal_soil_produces_info_severity_no_action(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-01", "Tomato",
            ph=6.4, nitrogen_ppm=40, phosphorus_ppm=30, potassium_ppm=200,
            source="lab_report",
        )
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("within the typical range", rec.problem)

    def test_acidic_soil_triggers_lime_recommendation(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-02", "Tomato",
            ph=4.8, nitrogen_ppm=40, phosphorus_ppm=30, potassium_ppm=200,
            source="lab_report",
        )
        self.assertIn("acidic", rec.problem.lower())
        self.assertIn("lime", rec.recommended_action.lower())

    def test_alkaline_soil_triggers_acidifying_recommendation(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-03", "Tomato",
            ph=8.2, nitrogen_ppm=40, phosphorus_ppm=30, potassium_ppm=200,
            source="lab_report",
        )
        self.assertIn("alkaline", rec.problem.lower())
        self.assertIn("sulfur", rec.recommended_action.lower())

    def test_low_nitrogen_triggers_fertilizer_recommendation(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-04", "Wheat",
            ph=6.5, nitrogen_ppm=5, phosphorus_ppm=25, potassium_ppm=180,
            source="lab_report",
        )
        self.assertIn("nitrogen", rec.problem.lower())
        self.assertIn("urea", rec.recommended_action.lower())

    def test_excess_potassium_flags_caution_without_more_fertilizer(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-05", "Wheat",
            ph=6.5, nitrogen_ppm=30, phosphorus_ppm=25, potassium_ppm=400,
            source="lab_report",
        )
        self.assertIn("potassium", rec.problem.lower())
        self.assertIn("already high", rec.problem.lower())

    def test_lab_report_has_higher_confidence_than_farmer_reported(self):
        rec_lab = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-06", "Tomato", ph=4.8, source="lab_report",
        )
        rec_farmer = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-07", "Tomato", ph=4.8, source="farmer_reported",
        )
        self.assertGreater(rec_lab.confidence, rec_farmer.confidence)

    def test_multiple_unverified_findings_escalate_to_expert(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-08", "Tomato",
            ph=4.5, nitrogen_ppm=5, phosphorus_ppm=5, potassium_ppm=20,
            source="farmer_reported",
        )
        self.assertTrue(rec.escalate_to_expert)

    def test_no_measurements_raises_agent_error(self):
        from backend.agents.base import AgentError
        with self.assertRaises(AgentError):
            self.orchestrator.handle_soil_test(self.farm_id, "FIELD-09", "Tomato")

    def test_unknown_crop_falls_back_to_default_profile_without_crashing(self):
        rec = self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-10", "Dragonfruit", ph=6.5, source="lab_report",
        )
        self.assertIsNotNone(rec)  # doesn't raise, degrades gracefully

    def test_soil_test_is_persisted_and_retrievable(self):
        self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-11", "Tomato", ph=6.4, source="lab_report",
        )
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-11", "Tomato")
        latest = self.memory.get_latest_soil_test(field_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["ph"], 6.4)

    def test_severe_soil_issue_creates_a_guardian_alert(self):
        self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-12", "Tomato",
            ph=4.5, nitrogen_ppm=5, phosphorus_ppm=5, potassium_ppm=20,
            source="lab_report",
        )
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        field_alerts = [a for a in alerts if a["subject_ref"] == "FIELD-12"]
        self.assertEqual(len(field_alerts), 1)
        self.assertEqual(field_alerts[0]["alert_type"], "soil_health")


if __name__ == "__main__":
    unittest.main(verbosity=2)
