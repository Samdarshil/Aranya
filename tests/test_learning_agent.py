"""
Learning Agent tests — run with: python3 tests/test_learning_agent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


class TestLearningAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_invalid_outcome_value_raises(self):
        with self.assertRaises(AgentError):
            self.orchestrator.handle_record_outcome(
                self.farm_id, None, "vision_agent", True, "definitely_better",
            )

    def test_below_sample_size_reports_insufficient_data_honestly(self):
        for _ in range(3):  # below MIN_SAMPLE_SIZE of 5
            self.orchestrator.handle_record_outcome(
                self.farm_id, None, "test_agent", True, "improved",
            )
        record = self.orchestrator.handle_agent_track_record(self.farm_id, "test_agent")
        self.assertFalse(record["sufficient_data"])
        self.assertNotIn("improved_pct", record)

    def test_sufficient_sample_computes_correct_percentages(self):
        # 5 followed: 3 improved, 1 no_change, 1 worsened
        outcomes = ["improved", "improved", "improved", "no_change", "worsened"]
        for outcome in outcomes:
            self.orchestrator.handle_record_outcome(self.farm_id, None, "test_agent", True, outcome)
        record = self.orchestrator.handle_agent_track_record(self.farm_id, "test_agent")
        self.assertTrue(record["sufficient_data"])
        self.assertEqual(record["improved_pct"], 60.0)
        self.assertEqual(record["no_change_pct"], 20.0)
        self.assertEqual(record["worsened_pct"], 20.0)

    def test_not_followed_outcomes_are_excluded_from_the_percentage_but_counted(self):
        for _ in range(5):
            self.orchestrator.handle_record_outcome(self.farm_id, None, "test_agent", True, "improved")
        for _ in range(2):
            self.orchestrator.handle_record_outcome(self.farm_id, None, "test_agent", False, "worsened")
        record = self.orchestrator.handle_agent_track_record(self.farm_id, "test_agent")
        self.assertEqual(record["improved_pct"], 100.0)  # only the 5 "followed" count toward the rate
        self.assertEqual(record["not_followed_count"], 2)

    def test_track_record_includes_the_observational_caveat(self):
        for _ in range(5):
            self.orchestrator.handle_record_outcome(self.farm_id, None, "test_agent", True, "improved")
        record = self.orchestrator.handle_agent_track_record(self.farm_id, "test_agent")
        self.assertIn("not a controlled comparison", record["caveat"].lower())

    def test_track_record_is_agent_specific(self):
        for _ in range(5):
            self.orchestrator.handle_record_outcome(self.farm_id, None, "agent_a", True, "improved")
        for _ in range(5):
            self.orchestrator.handle_record_outcome(self.farm_id, None, "agent_b", True, "worsened")
        record_a = self.orchestrator.handle_agent_track_record(self.farm_id, "agent_a")
        record_b = self.orchestrator.handle_agent_track_record(self.farm_id, "agent_b")
        self.assertEqual(record_a["improved_pct"], 100.0)
        self.assertEqual(record_b["improved_pct"], 0.0)

    def test_integration_with_a_real_vision_recommendation(self):
        # Full loop: real crop scan -> real recommendation_id -> outcome
        # recorded against it -> shows up in the farm's own outcome log.
        img = Image.open(SAMPLES / "crop" / "tomato_severe.jpg")
        bgr = pil_to_bgr(img)
        self.orchestrator.handle_crop_scan(self.farm_id, bgr, "FIELD-01", "Tomato", is_demo=True)
        recs = self.memory.get_farm_recommendations(self.farm_id)
        rec_id = recs[0]["id"]

        self.orchestrator.handle_record_outcome(
            self.farm_id, rec_id, "vision_agent", True, "improved",
            notes="Applied recommended fungicide, blight cleared up in a week.",
        )
        farm_outcomes = self.memory.get_farm_outcomes(self.farm_id)
        self.assertEqual(len(farm_outcomes), 1)
        self.assertEqual(farm_outcomes[0]["recommendation_id"], rec_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
