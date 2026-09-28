"""
Intent Router tests — run with: python3 tests/test_intent_router.py

These test the part that's actually risky: what happens when the LLM
(simulated here by a fake provider returning canned strings) produces
malformed, incomplete, or invented output. A real Gemini call would
usually behave — these tests are specifically about the cases where it
doesn't.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agents.intent_router import Intent, IntentRouter
from backend.core.llm_provider import LLMUnavailable


class FakeLLMProvider:
    """Returns a canned string regardless of input — conforms to the
    LLMProvider protocol without any network call."""
    name = "fake_llm"

    def __init__(self, canned_response: str):
        self._response = canned_response

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self._response


class TestIntentRouter(unittest.TestCase):
    def test_valid_weather_intent(self):
        router = IntentRouter(FakeLLMProvider('{"action": "weather_check", "params": {}, "clarification_needed": null}'))
        intent = router.parse_message("what's the weather like today")
        self.assertEqual(intent.action, "weather_check")

    def test_valid_field_history_intent_with_params(self):
        router = IntentRouter(FakeLLMProvider(
            '{"action": "field_history", "params": {"field_ref": "FIELD-01", "crop_name": "Tomato"}, '
            '"clarification_needed": null}'
        ))
        intent = router.parse_message("pichli baar FIELD-01 mein kya hua tha")
        self.assertEqual(intent.action, "field_history")
        self.assertEqual(intent.params["field_ref"], "FIELD-01")
        self.assertEqual(intent.params["crop_name"], "Tomato")

    def test_markdown_fenced_json_is_still_parsed(self):
        router = IntentRouter(FakeLLMProvider(
            '```json\n{"action": "weather_check", "params": {}, "clarification_needed": null}\n```'
        ))
        intent = router.parse_message("weather?")
        self.assertEqual(intent.action, "weather_check")

    def test_malformed_json_degrades_to_unclear_not_a_crash(self):
        router = IntentRouter(FakeLLMProvider("this is not json at all {broken"))
        intent = router.parse_message("something")
        self.assertEqual(intent.action, "unclear")
        self.assertIsNotNone(intent.clarification_needed)

    def test_invented_action_name_degrades_to_unclear(self):
        # The LLM hallucinates an action not in our allowed set.
        router = IntentRouter(FakeLLMProvider(
            '{"action": "launch_missiles", "params": {}, "clarification_needed": null}'
        ))
        intent = router.parse_message("something")
        self.assertEqual(intent.action, "unclear")

    def test_missing_required_param_degrades_to_unclear_with_explanation(self):
        # planning_query requires field_ref and crop_name — LLM only gave crop_name.
        router = IntentRouter(FakeLLMProvider(
            '{"action": "planning_query", "params": {"crop_name": "Wheat"}, "clarification_needed": null}'
        ))
        intent = router.parse_message("should I plant wheat")
        self.assertEqual(intent.action, "unclear")
        self.assertIn("field_ref", intent.clarification_needed)

    def test_explicit_unclear_with_clarification_is_passed_through(self):
        router = IntentRouter(FakeLLMProvider(
            '{"action": "unclear", "params": {}, "clarification_needed": "Which field do you mean?"}'
        ))
        intent = router.parse_message("check on it")
        self.assertEqual(intent.action, "unclear")
        self.assertEqual(intent.clarification_needed, "Which field do you mean?")

    def test_no_provider_configured_raises_instead_of_guessing(self):
        router = IntentRouter(llm=None)
        with self.assertRaises(LLMUnavailable):
            router.parse_message("what's the weather")

    def test_non_dict_params_does_not_crash(self):
        # LLM returns params as a string instead of an object — malformed but shouldn't crash.
        router = IntentRouter(FakeLLMProvider(
            '{"action": "weather_check", "params": "not a dict", "clarification_needed": null}'
        ))
        intent = router.parse_message("weather?")
        self.assertEqual(intent.action, "weather_check")
        self.assertEqual(intent.params, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
