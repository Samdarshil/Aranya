"""
End-to-end test of the core Aranya loop (spec section 34):

    Farmer -> Input (photo) -> Orchestrator -> Vision Agent -> Evidence
            -> Recommendation -> Farm Memory -> "what happened last time?"

Run with:  python3 tests/test_vertical_slice.py
(plain unittest — no pytest in this sandbox; works unmodified with pytest
 elsewhere too.)
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
from backend.core.schemas import Severity
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


class TestVerticalSlice(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "test_aranya.db"
        self.memory = FarmMemory(db_path=db_path)
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer", phone="+91-9999900000")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _load(self, rel_path: str):
        img = Image.open(SAMPLES / rel_path)
        return pil_to_bgr(img)

    def test_crop_scan_produces_structured_recommendation(self):
        bgr = self._load("crop/tomato_severe.jpg")
        rec = self.orchestrator.handle_crop_scan(self.farm_id, bgr, "FIELD-01", "Tomato", is_demo=True)

        self.assertEqual(rec.severity, Severity.HIGH)
        self.assertTrue(rec.escalate_to_expert)
        self.assertGreater(len(rec.evidence), 0)
        # Every evidence item must carry attribution — no unattributed claims.
        for ev in rec.evidence:
            self.assertIsNotNone(ev.source)
        # Structured summary must answer the explainability questions (spec section 14).
        summary = rec.as_farmer_summary()
        for key in ("what_happened", "why_it_matters", "evidence", "what_to_do", "how_urgent"):
            self.assertIn(key, summary)

    def test_recommendation_rejects_empty_evidence(self):
        from backend.core.schemas import Recommendation, Severity, Urgency
        with self.assertRaises(ValueError):
            Recommendation(
                problem="x", evidence=(), confidence=0.9, severity=Severity.LOW,
                urgency=Urgency.NONE, recommended_action="y", reasoning="z",
            )

    def test_field_history_accumulates_across_scans(self):
        # Re-scanning the same field over "time" should build real history —
        # this is the mechanism behind "pichli baar is field mein kya hua tha?"
        self.orchestrator.handle_crop_scan(self.farm_id, self._load("crop/tomato_healthy.jpg"),
                                            "FIELD-02", "Tomato", is_demo=True)
        self.orchestrator.handle_crop_scan(self.farm_id, self._load("crop/tomato_moderate.jpg"),
                                            "FIELD-02", "Tomato", is_demo=True)
        result = self.orchestrator.handle_field_history_query(self.farm_id, "FIELD-02", "Tomato")

        self.assertEqual(result["scan_count"], 2)
        self.assertEqual(result["latest_status"], "At Risk")

    def test_livestock_baseline_improves_with_history(self):
        # First observation: no baseline exists yet.
        rec1 = self.orchestrator.handle_livestock_scan(
            self.farm_id, self._load("livestock/cow001_day1_normal.jpg"), "COW-001", "Cow", is_demo=True,
        )
        self.assertFalse(any(e.source.value == "farm_memory" for e in rec1.evidence))

        # Second observation: baseline now exists and is cited as evidence.
        rec2 = self.orchestrator.handle_livestock_scan(
            self.farm_id, self._load("livestock/cow001_day5_normal.jpg"), "COW-001", "Cow", is_demo=True,
        )
        self.assertTrue(any(e.source.value == "farm_memory" for e in rec2.evidence))

    def test_skin_patch_always_escalates(self):
        rec = self.orchestrator.handle_livestock_scan(
            self.farm_id, self._load("livestock/cow003_day1_skin_patch.jpg"), "COW-003", "Cow", is_demo=True,
        )
        self.assertTrue(rec.escalate_to_expert)
        self.assertIn("veterinarian", rec.escalation_reason.lower())

    def test_history_query_on_never_scanned_field_is_honest(self):
        result = self.orchestrator.handle_field_history_query(self.farm_id, "FIELD-NEVER-SEEN", "Wheat")
        self.assertEqual(result["scan_count"], 0)
        self.assertIn("No scans recorded", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
