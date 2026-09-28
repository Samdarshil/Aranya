"""
Voice pipeline tests — run with: python3 tests/test_voice_agent.py

Two things are genuinely testable here without real audio: the language
detection logic (pure text classification), and the orchestration logic
around STT/TTS (with fake providers standing in for the actual speech
APIs, same pattern as test_weather_agent.py's FakeWeatherProvider).
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
from backend.core.language_detection import DetectedLanguage, detect_language
from backend.core.voice_provider import VoiceUnavailable
from backend.memory.store import FarmMemory


class TestLanguageDetection(unittest.TestCase):
    def test_pure_english(self):
        self.assertEqual(detect_language("What is the weather today?"), DetectedLanguage.ENGLISH)

    def test_pure_hindi_devanagari(self):
        self.assertEqual(detect_language("आज मौसम कैसा है?"), DetectedLanguage.HINDI)

    def test_code_mixed_devanagari_and_latin(self):
        self.assertEqual(
            detect_language("मेरे खेत में FIELD-01 mein kya hua"), DetectedLanguage.CODE_MIXED,
        )

    def test_empty_string_is_unknown(self):
        self.assertEqual(detect_language(""), DetectedLanguage.UNKNOWN)

    def test_whitespace_only_is_unknown(self):
        self.assertEqual(detect_language("   "), DetectedLanguage.UNKNOWN)

    def test_numbers_only_is_unknown(self):
        self.assertEqual(detect_language("12345"), DetectedLanguage.UNKNOWN)

    def test_documented_limitation_romanized_hindi_reads_as_english(self):
        # This is the documented limitation in the module — confirmed
        # here so it can't silently regress into an undocumented one.
        self.assertEqual(detect_language("FIELD-01 mein kya hua tha"), DetectedLanguage.ENGLISH)


@dataclass
class FakeSTTProvider:
    name: str = "fake_stt"
    canned_transcript: str | None = None
    should_fail: bool = False

    def transcribe(self, audio_bytes: bytes, language_hint: str | None = None) -> str:
        if self.should_fail or self.canned_transcript is None:
            raise VoiceUnavailable("no transcript configured for this test")
        return self.canned_transcript


@dataclass
class FakeTTSProvider:
    name: str = "fake_tts"
    should_fail: bool = False

    def synthesize(self, text: str, language: str) -> bytes:
        if self.should_fail:
            raise VoiceUnavailable("tts failed for this test")
        return f"AUDIO[{language}]:{text}".encode()


class TestVoiceAgentThroughOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_stt_provider_fails_honestly(self):
        orch = Orchestrator.default(memory=self.memory)  # no stt_provider
        with self.assertRaises(AgentError) as ctx:
            orch.handle_voice_message(self.farm_id, b"fake audio bytes")
        self.assertIn("No speech-to-text provider", str(ctx.exception))

    def test_stt_failure_propagates_as_retryable(self):
        orch = Orchestrator.default(memory=self.memory, stt_provider=FakeSTTProvider(should_fail=True))
        with self.assertRaises(AgentError) as ctx:
            orch.handle_voice_message(self.farm_id, b"garbled audio")
        self.assertTrue(ctx.exception.retryable)

    def test_empty_transcript_is_rejected(self):
        orch = Orchestrator.default(memory=self.memory, stt_provider=FakeSTTProvider(canned_transcript="   "))
        with self.assertRaises(AgentError):
            orch.handle_voice_message(self.farm_id, b"silence")

    def test_transcribed_text_flows_through_the_real_conversational_pipeline(self):
        # No LLM configured, so the underlying handle_farmer_message call
        # will honestly fail to classify intent — but that's the REAL
        # pipeline being exercised, not a voice-specific shortcut.
        orch = Orchestrator.default(
            memory=self.memory, stt_provider=FakeSTTProvider(canned_transcript="what's the weather"),
        )
        result = orch.handle_voice_message(self.farm_id, b"audio")
        self.assertEqual(result["transcript"], "what's the weather")
        self.assertEqual(result["type"], "error")  # no LLM configured — same as the text-chat test expects
        self.assertIn("No LLM provider", result["message"])

    def test_detected_language_is_included_in_the_result(self):
        orch = Orchestrator.default(
            memory=self.memory, stt_provider=FakeSTTProvider(canned_transcript="आज मौसम कैसा है"),
        )
        result = orch.handle_voice_message(self.farm_id, b"audio")
        self.assertEqual(result["detected_language"], "hi")

    def test_tts_reply_is_synthesized_when_configured(self):
        from dataclasses import dataclass as dc

        @dc
        class FakeLLM:
            name: str = "fake_llm"
            def generate(self, system_prompt, user_prompt):
                return '{"action": "weather_check", "params": {}, "clarification_needed": null}'

        from backend.core.providers import ProviderUnavailable, WeatherReading

        @dc
        class FakeWeather:
            name: str = "fake_weather"
            def get_current(self, lat, lng): return self.get_forecast(lat, lng)
            def get_forecast(self, lat, lng, hours_ahead=24):
                import datetime as dt
                return WeatherReading(
                    observed_at=dt.datetime.now(dt.timezone.utc), temperature_c=28.0, humidity_pct=60.0,
                    rainfall_last_24h_mm=0.0, rainfall_forecast_24h_mm=0.0, wind_speed_kmh=10.0,
                    provider="fake_weather", is_forecast=True,
                )

        orch = Orchestrator.default(
            memory=self.memory,
            stt_provider=FakeSTTProvider(canned_transcript="what's the weather"),
            tts_provider=FakeTTSProvider(),
            llm_provider=FakeLLM(),
            weather_provider=FakeWeather(),
        )
        result = orch.handle_voice_message(self.farm_id, b"audio", lat=19.07, lng=72.87)
        self.assertTrue(result["audio_reply_available"])
        self.assertIn(b"AUDIO[", result["_audio_reply_bytes"])

    def test_missing_tts_degrades_gracefully_without_losing_the_text_reply(self):
        from dataclasses import dataclass as dc

        @dc
        class FakeLLM:
            name: str = "fake_llm"
            def generate(self, system_prompt, user_prompt):
                return '{"action": "unclear", "params": {}, "clarification_needed": "Which field?"}'

        orch = Orchestrator.default(
            memory=self.memory,
            stt_provider=FakeSTTProvider(canned_transcript="check on it"),
            llm_provider=FakeLLM(),
            # no tts_provider passed
        )
        result = orch.handle_voice_message(self.farm_id, b"audio")
        self.assertEqual(result["type"], "clarification")
        self.assertEqual(result["message"], "Which field?")
        self.assertFalse(result["audio_reply_available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
