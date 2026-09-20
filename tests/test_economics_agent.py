"""
Economics Agent tests — run with: python3 tests/test_economics_agent.py
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
from backend.core.schemas import Severity
from backend.memory.store import FarmMemory


class TestEconomicsAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_data_raises_rather_than_reporting_zero(self):
        with self.assertRaises(AgentError):
            self.orchestrator.handle_field_economics(self.farm_id, "FIELD-01", "Tomato")

    def test_expenses_only_reports_spend_not_a_loss(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-02", "Tomato", "seed", 2000)
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-02", "Tomato", "fertilizer", 1500)
        rec = self.orchestrator.handle_field_economics(self.farm_id, "FIELD-02", "Tomato")
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("nothing sold yet", rec.problem.lower())
        self.assertNotIn("loss", rec.problem.lower())

    def test_sales_only_reports_revenue_not_profit(self):
        self.orchestrator.handle_log_sale(self.farm_id, "FIELD-03", "Tomato", 500, 20)
        rec = self.orchestrator.handle_field_economics(self.farm_id, "FIELD-03", "Tomato")
        self.assertIn("no expenses on record", rec.problem.lower())

    def test_profitable_field_reports_correctly(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-04", "Tomato", "seed", 2000)
        self.orchestrator.handle_log_sale(self.farm_id, "FIELD-04", "Tomato", 500, 20)  # 10000 revenue
        rec = self.orchestrator.handle_field_economics(self.farm_id, "FIELD-04", "Tomato")
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("profit", rec.problem.lower())
        self.assertNotIn("-", rec.problem.split("\u20b9")[1][:6])  # profit figure isn't negative

    def test_significant_loss_flags_moderate_severity(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-05", "Tomato", "seed", 8000)
        self.orchestrator.handle_log_sale(self.farm_id, "FIELD-05", "Tomato", 200, 20)  # 4000 revenue
        rec = self.orchestrator.handle_field_economics(self.farm_id, "FIELD-05", "Tomato")
        self.assertEqual(rec.severity, Severity.MODERATE)
        self.assertIn("loss", rec.problem.lower())

    def test_expense_breakdown_by_category_is_in_evidence(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-06", "Tomato", "seed", 1000)
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-06", "Tomato", "labor", 3000)
        self.orchestrator.handle_log_sale(self.farm_id, "FIELD-06", "Tomato", 500, 20)
        rec = self.orchestrator.handle_field_economics(self.farm_id, "FIELD-06", "Tomato")
        evidence_text = " ".join(e.description for e in rec.evidence)
        self.assertIn("labor", evidence_text.lower())
        self.assertIn("seed", evidence_text.lower())

    def test_multiple_expenses_accumulate_correctly(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-07", "Tomato", "seed", 500)
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-07", "Tomato", "fertilizer", 700)
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-07", "Tomato", "labor", 300)
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-07", "Tomato")
        total = sum(e["amount"] for e in self.memory.get_field_expenses(field_id))
        self.assertEqual(total, 1500)

    def test_significant_loss_creates_a_guardian_alert(self):
        self.orchestrator.handle_log_expense(self.farm_id, "FIELD-08", "Tomato", "seed", 8000)
        self.orchestrator.handle_log_sale(self.farm_id, "FIELD-08", "Tomato", 200, 20)
        self.orchestrator.handle_field_economics(self.farm_id, "FIELD-08", "Tomato")
        alerts = self.orchestrator.get_active_alerts(self.farm_id)
        econ_alerts = [a for a in alerts if a["alert_type"] == "economics"]
        self.assertEqual(len(econ_alerts), 1)

    def test_replanting_starts_a_fresh_cycle_so_seasons_dont_blend(self):
        # This is the exact gap flagged in docs/STATUS.md before this fix:
        # a replanted field's old and new season costs/sales used to blend
        # together in Economics. Now they must not.
        field_ref = "FIELD-09"

        # Season 1: Tomato, profitable.
        self.orchestrator.handle_log_expense(self.farm_id, field_ref, "Tomato", "seed", 1000)
        self.orchestrator.handle_log_sale(self.farm_id, field_ref, "Tomato", 500, 20)  # 10000 revenue
        rec_season1 = self.orchestrator.handle_field_economics(self.farm_id, field_ref, "Tomato")
        self.assertIn("profit", rec_season1.problem.lower())

        # Farmer replants with Wheat.
        self.orchestrator.handle_start_new_crop_cycle(self.farm_id, field_ref, "Wheat")

        # Season 2: Wheat, only costs logged so far — should NOT show
        # season 1's Tomato profit blended in.
        self.orchestrator.handle_log_expense(self.farm_id, field_ref, "Wheat", "seed", 500)
        rec_season2 = self.orchestrator.handle_field_economics(self.farm_id, field_ref, "Wheat")
        self.assertIn("nothing sold yet", rec_season2.problem.lower())
        self.assertIn("500", rec_season2.problem)  # only this cycle's 500, not blended with season 1

        # All-time totals (a different, explicit query) should still show
        # both seasons — the fix is about NOT blending by default, not
        # about losing historical data.
        field_id = self.memory.get_or_create_field(self.farm_id, field_ref, "Wheat")
        all_time_expenses = sum(e["amount"] for e in self.memory.get_field_expenses(field_id))
        self.assertEqual(all_time_expenses, 1500)  # 1000 (season 1) + 500 (season 2)

    def test_active_cycle_is_auto_created_without_explicit_management(self):
        # Callers who never explicitly start a cycle still get correctly
        # isolated per-field data from the very first expense logged.
        field_ref = "FIELD-10"
        self.orchestrator.handle_log_expense(self.farm_id, field_ref, "Tomato", "seed", 300)
        field_id = self.memory.get_or_create_field(self.farm_id, field_ref, "Tomato")
        cycle = self.memory.get_active_crop_cycle(field_id)
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle["crop_name"], "Tomato")


if __name__ == "__main__":
    unittest.main(verbosity=2)
