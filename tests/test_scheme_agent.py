"""
Scheme Agent tests — run with: python3 tests/test_scheme_agent.py
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


class TestSchemeAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_input_raises(self):
        with self.assertRaises(AgentError):
            self.orchestrator.handle_scheme_match(self.farm_id)

    def test_universal_schemes_match_regardless_of_land_size(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=50, category="general")
        self.assertIn("PM-KISAN", rec.recommended_action)
        self.assertIn("KCC", rec.recommended_action)

    def test_small_holding_sc_category_matches_the_enhanced_subsidy_scheme(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=3, category="sc")
        self.assertIn("SMAM", rec.recommended_action)

    def test_large_holding_general_category_excludes_the_enhanced_subsidy_scheme(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=20, category="general")
        self.assertNotIn("SMAM", rec.recommended_action)

    def test_every_recommendation_includes_the_staleness_caveat(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=3, category="general")
        self.assertIn("not a live government feed", rec.reasoning.lower())
        self.assertIn("confirm", rec.reasoning.lower())

    def test_confidence_is_deliberately_capped_not_high(self):
        # This agent should never claim high confidence about scheme
        # matching given it's a curated, possibly-stale reference list.
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=3, category="general")
        self.assertLess(rec.confidence, 0.6)

    def test_land_only_no_category_still_works(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, land_acres=3)
        self.assertGreater(len(rec.evidence), 1)  # at least the summary + one matched scheme

    def test_category_only_no_land_still_works(self):
        rec = self.orchestrator.handle_scheme_match(self.farm_id, category="marginal")
        self.assertGreater(len(rec.evidence), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
