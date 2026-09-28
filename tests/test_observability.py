"""
Observability tests — run with: python3 tests/test_observability.py

Tests two things: the trace_agent_call context manager in isolation
(duration measurement, exception propagation), and — more importantly —
that it actually fires with the right fields when real Orchestrator
methods run, both on success and on failure.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.core.observability import get_logger, trace_agent_call
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            pass  # non-JSON log lines (shouldn't happen for agent_call events)


class TestTraceAgentCallInIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = _CaptureHandler()
        self.logger = get_logger()
        self._original_handlers = self.logger.handlers
        self.logger.handlers = [self.handler]

    def tearDown(self) -> None:
        self.logger.handlers = self._original_handlers

    def test_successful_call_logs_success_true_with_duration(self):
        with trace_agent_call(farm_id=1, agent="test_agent", operation="test_op", logger=self.logger):
            time.sleep(0.01)
        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertTrue(record["success"])
        self.assertGreater(record["duration_ms"], 0)
        self.assertEqual(record["agent"], "test_agent")
        self.assertEqual(record["farm_id"], 1)
        self.assertNotIn("error", record)

    def test_exception_still_logs_and_still_propagates(self):
        with self.assertRaises(ValueError):
            with trace_agent_call(farm_id=1, agent="test_agent", operation="test_op", logger=self.logger):
                raise ValueError("boom")
        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertFalse(record["success"])
        self.assertIn("ValueError", record["error"])
        self.assertIn("boom", record["error"])


class TestObservabilityThroughRealOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

        self.handler = _CaptureHandler()
        self.logger = get_logger()
        self._original_handlers = self.logger.handlers
        self.logger.handlers = [self.handler]

    def tearDown(self) -> None:
        self.logger.handlers = self._original_handlers
        self._tmpdir.cleanup()

    def test_real_crop_scan_is_traced(self):
        img = Image.open(SAMPLES / "crop" / "tomato_healthy.jpg")
        bgr = pil_to_bgr(img)
        self.orchestrator.handle_crop_scan(self.farm_id, bgr, "FIELD-01", "Tomato", is_demo=True)

        agent_calls = [r for r in self.handler.records if r.get("agent") == "vision_agent"]
        self.assertEqual(len(agent_calls), 1)
        self.assertEqual(agent_calls[0]["operation"], "analyze_crop")
        self.assertTrue(agent_calls[0]["success"])

    def test_failed_agent_call_is_traced_as_failure(self):
        # No weather provider configured — WeatherAgent will raise AgentError.
        with self.assertRaises(AgentError):
            self.orchestrator.handle_weather_check(self.farm_id, lat=19.07, lng=72.87)

        weather_calls = [r for r in self.handler.records if r.get("agent") == "weather_agent"]
        self.assertEqual(len(weather_calls), 1)
        self.assertFalse(weather_calls[0]["success"])
        self.assertIn("AgentError", weather_calls[0]["error"])

    def test_multiple_different_agents_each_get_their_own_traced_call(self):
        self.orchestrator.handle_soil_test(self.farm_id, "FIELD-02", "Tomato", ph=6.4, source="lab_report")
        self.orchestrator.handle_scheme_match(self.farm_id, land_acres=3, category="general")

        agents_traced = {r["agent"] for r in self.handler.records}
        self.assertIn("soil_agent", agents_traced)
        self.assertIn("scheme_agent", agents_traced)

    def test_trace_does_not_alter_the_returned_recommendation(self):
        # Observability wrapping a call site must be transparent — the
        # actual return value shouldn't change at all.
        img = Image.open(SAMPLES / "crop" / "tomato_severe.jpg")
        bgr = pil_to_bgr(img)
        rec = self.orchestrator.handle_crop_scan(self.farm_id, bgr, "FIELD-03", "Tomato", is_demo=True)
        self.assertEqual(rec.source_agent, "vision_agent")
        self.assertTrue(len(rec.evidence) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
