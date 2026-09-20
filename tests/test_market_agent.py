"""
Market Agent tests — run with: python3 tests/test_market_agent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.core.providers import MarketPriceReading, ProviderUnavailable
from backend.core.schemas import Severity
from backend.memory.store import FarmMemory


@dataclass
class FakeMarketProvider:
    name: str = "fake_market"
    price_sequence: list = None  # list of floats, popped in order
    _calls: int = 0

    def get_latest_price(self, crop_name: str, market_name: str) -> MarketPriceReading:
        import datetime as dt
        if not self.price_sequence:
            raise ProviderUnavailable("no price configured")
        price = self.price_sequence[self._calls % len(self.price_sequence)]
        self._calls += 1
        return MarketPriceReading(
            crop_name=crop_name, market_name=market_name, price_per_quintal=price,
            recorded_at=dt.datetime.now(dt.timezone.utc), provider=self.name,
        )


class TestMarketAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _orchestrator(self, prices):
        return Orchestrator.default(memory=self.memory, market_provider=FakeMarketProvider(price_sequence=prices))

    def test_no_provider_configured_raises_instead_of_fabricating(self):
        orch = Orchestrator.default(memory=self.memory)  # no market_provider
        with self.assertRaises(AgentError):
            orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")

    def test_first_check_has_no_trend_yet(self):
        orch = self._orchestrator([2000])
        rec = orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("no trend data yet", rec.problem.lower())

    def test_price_spike_above_average_recommends_selling(self):
        orch = self._orchestrator([2000, 2000, 2000, 2400])  # ~20% spike on 4th check
        for _ in range(4):
            rec = orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        self.assertIn("above", rec.problem.lower())
        self.assertIn("sell", rec.recommended_action.lower())

    def test_price_drop_below_average_recommends_holding(self):
        orch = self._orchestrator([2000, 2000, 2000, 1600])  # ~20% drop on 4th check
        for _ in range(4):
            rec = orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        self.assertIn("below", rec.problem.lower())
        self.assertIn("hold", rec.recommended_action.lower())

    def test_stable_price_gives_neutral_recommendation(self):
        orch = self._orchestrator([2000, 2010, 1995, 2005])  # small fluctuations
        for _ in range(4):
            rec = orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        self.assertEqual(rec.severity, Severity.INFO)
        self.assertIn("no strong signal", rec.recommended_action.lower())

    def test_price_history_persists_across_checks(self):
        orch = self._orchestrator([2000, 2100, 2200])
        for _ in range(3):
            orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        history = self.memory.get_market_price_history("Wheat", "Delhi Mandi")
        self.assertEqual(len(history), 3)

    def test_significant_spike_creates_a_guardian_alert(self):
        orch = self._orchestrator([2000, 2000, 2000, 2500])
        for _ in range(4):
            orch.handle_market_check(self.farm_id, "Wheat", "Delhi Mandi")
        alerts = orch.get_active_alerts(self.farm_id)
        market_alerts = [a for a in alerts if a["alert_type"] == "market_price"]
        self.assertEqual(len(market_alerts), 1)

    def test_chat_market_question_does_not_crash_when_no_provider_configured(self):
        # Regression test: handle_farmer_message must catch AgentError from
        # every dispatch path (weather/planning/market), not just market —
        # verified here for market since it's the newest path, and the
        # same fix now covers weather_check and planning_query too.
        from dataclasses import dataclass as dc

        @dc
        class FakeLLM:
            name: str = "fake_llm"
            def generate(self, system_prompt, user_prompt):
                return ('{"action": "market_check", "params": {"crop_name": "Wheat", '
                        '"market_name": "Delhi Mandi"}, "clarification_needed": null}')

        orch = Orchestrator.default(memory=self.memory, llm_provider=FakeLLM())  # no market provider
        result = orch.handle_farmer_message(self.farm_id, "what's the wheat price in Delhi Mandi")
        self.assertEqual(result["type"], "error")
        self.assertIn("No market data provider", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
