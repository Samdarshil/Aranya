"""
Expert Escalation Agent tests — run with: python3 tests/test_expert_escalation.py

Tests that the escalate_to_expert flag other agents already set now
actually DOES something — creates a tracked, resolvable consultation
request — rather than just sitting unused in the Recommendation object.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from backend.agents.orchestrator import Orchestrator
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


class TestExpertEscalation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _crop_bgr(self, name: str):
        return pil_to_bgr(Image.open(SAMPLES / "crop" / f"{name}.jpg"))

    def _livestock_bgr(self, name: str):
        return pil_to_bgr(Image.open(SAMPLES / "livestock" / f"{name}.jpg"))

    def test_high_severity_crop_scan_creates_a_consultation(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-01", "Tomato", is_demo=True)
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["source_agent"], "vision_agent")
        self.assertEqual(pending[0]["status"], "pending")

    def test_skin_patch_livestock_scan_creates_a_consultation(self):
        self.orchestrator.handle_livestock_scan(self.farm_id, self._livestock_bgr("cow003_day1_skin_patch"),
                                                  "COW-003", "Cow", is_demo=True)
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending), 1)
        self.assertIn("veterinarian", pending[0]["escalation_reason"].lower())

    def test_healthy_scan_does_not_create_a_consultation(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_healthy"),
                                            "FIELD-02", "Tomato", is_demo=True)
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending), 0)

    def test_multiple_unverified_soil_findings_creates_a_consultation(self):
        self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-03", "Tomato",
            ph=4.5, nitrogen_ppm=5, phosphorus_ppm=5, potassium_ppm=20,
            source="farmer_reported",
        )
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["source_agent"], "soil_agent")

    def test_resolve_workflow_moves_consultation_out_of_pending_queue(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-04", "Tomato", is_demo=True)
        pending_before = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending_before), 1)
        consultation_id = pending_before[0]["id"]

        result = self.orchestrator.resolve_consultation(
            self.farm_id, consultation_id, "Dr. Sharma", "Confirmed early blight, recommend copper fungicide.",
        )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["expert_name"], "Dr. Sharma")

        pending_after = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending_after), 0)

    def test_resolving_nonexistent_consultation_raises(self):
        with self.assertRaises(ValueError):
            self.orchestrator.resolve_consultation(self.farm_id, 99999, "Dr. Sharma", "notes")

    def test_resolving_another_farms_consultation_raises(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-05", "Tomato", is_demo=True)
        consultation_id = self.orchestrator.get_pending_consultations(self.farm_id)[0]["id"]

        other_farmer_id = self.memory.get_or_create_farmer("Other Farmer", phone="+91-other")
        other_farm_id = self.memory.get_or_create_farm(other_farmer_id, "Other Farm")
        with self.assertRaises(ValueError):
            self.orchestrator.resolve_consultation(other_farm_id, consultation_id, "Dr. Sharma", "notes")

    def test_queue_is_prioritized_by_severity(self):
        # A moderate-severity soil issue and a high-severity crop issue —
        # the high one should come first in the queue regardless of order created.
        self.orchestrator.handle_soil_test(
            self.farm_id, "FIELD-06", "Tomato",
            ph=4.5, nitrogen_ppm=5, phosphorus_ppm=5, potassium_ppm=20,
            source="farmer_reported",
        )
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-07", "Tomato", is_demo=True)
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["source_agent"], "vision_agent")  # high severity first

    def test_consultation_links_back_to_the_originating_recommendation(self):
        self.orchestrator.handle_crop_scan(self.farm_id, self._crop_bgr("tomato_severe"),
                                            "FIELD-08", "Tomato", is_demo=True)
        pending = self.orchestrator.get_pending_consultations(self.farm_id)
        self.assertIsNotNone(pending[0]["recommendation_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
