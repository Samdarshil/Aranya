"""
Research Agent tests — run with: python3 tests/test_research_agent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.memory.store import FarmMemory


class TestResearchAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_empty_query_raises(self):
        with self.assertRaises(AgentError):
            self.orchestrator.handle_research_query(self.farm_id, "")

    def test_realistic_symptom_description_matches_correct_entry(self):
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "white powdery coating on my tomato leaves",
        )
        self.assertIn("Powdery mildew", rec.problem)

    def test_bollworm_query_matches_correctly(self):
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "small holes appearing in my cotton bolls",
        )
        self.assertIn("Bollworm", rec.problem)

    def test_nonsense_query_returns_honest_no_match(self):
        rec = self.orchestrator.handle_research_query(self.farm_id, "asdf qwerty xyz123")
        self.assertIn("No close match", rec.problem)
        self.assertIn("photo scan", rec.recommended_action.lower())

    def test_crop_filter_excludes_non_matching_crop_entries(self):
        # Bollworm affects Cotton/Tomato/Maize but not Wheat — filtering
        # to Wheat should not surface it even with matching keywords.
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "holes in my crop", crop_name="Wheat",
        )
        self.assertNotIn("Bollworm", rec.problem)

    def test_confidence_is_never_high_for_a_text_only_match(self):
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "white powdery coating on my tomato leaves",
        )
        self.assertLessEqual(rec.confidence, 0.6)

    def test_late_blight_match_escalates_to_expert(self):
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "water soaked dark patches spreading fast with white fuzzy growth",
        )
        self.assertIn("Late blight", rec.problem)
        self.assertTrue(rec.escalate_to_expert)

    def test_query_is_logged_to_farm_timeline(self):
        self.orchestrator.handle_research_query(self.farm_id, "yellow rust spots on wheat leaves")
        timeline = self.memory.get_farm_timeline(self.farm_id)
        self.assertTrue(any(e["event_type"] == "research_query" for e in timeline))

    def test_reasoning_always_distinguishes_from_a_photo_diagnosis(self):
        rec = self.orchestrator.handle_research_query(
            self.farm_id, "white powdery coating on my tomato leaves",
        )
        self.assertIn("not a diagnosis", rec.reasoning.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
