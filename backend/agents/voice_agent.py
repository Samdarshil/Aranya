"""
Voice Agent — spec section 16.

Deliberately thin: transcription (STT) and language detection are real
and testable here (with a fake provider standing in for the STT call
itself, same pattern as WeatherAgent/MarketAgent tests). The actual
"understand what the farmer wants and do it" logic is NOT duplicated
here — that's Orchestrator.handle_farmer_message, already built and
tested. This agent's job is narrowly: turn audio into text (and know
what language it's in), and optionally turn a text reply back into
audio. Everything in between reuses the existing conversational pipeline.

TTS is optional and degrades gracefully — a voice interface should still
work as "speak in, read text reply" even if speech-out isn't configured,
rather than failing the whole interaction over a missing nice-to-have.
STT is NOT optional — with no transcript, there is no farmer message to
act on, so that failure propagates (spec section 3: no fabricated input).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.language_detection import DetectedLanguage, detect_language
from backend.core.voice_provider import SpeechToTextProvider, TextToSpeechProvider, VoiceUnavailable


@dataclass(frozen=True)
class Transcript:
    text: str
    detected_language: DetectedLanguage


class VoiceAgent(Agent):
    name = "voice_agent"

    def __init__(self, stt_provider: SpeechToTextProvider | None = None,
                 tts_provider: TextToSpeechProvider | None = None):
        self._stt = stt_provider
        self._tts = tts_provider

    def run(self, context: AgentContext, **kwargs) -> Transcript:
        return self.transcribe(context, **kwargs)

    def transcribe(self, context: AgentContext, audio_bytes: bytes,
                    language_hint: str | None = None) -> Transcript:
        if self._stt is None:
            raise AgentError(
                "No speech-to-text provider is configured (GOOGLE_SPEECH_API_KEY unset). "
                "Voice input is unavailable — no transcript has been fabricated.",
                retryable=False,
            )
        try:
            text = self._stt.transcribe(audio_bytes, language_hint)
        except VoiceUnavailable as exc:
            raise AgentError(f"Speech-to-text failed: {exc}", retryable=True) from exc

        if not text or not text.strip():
            raise AgentError(
                "No speech was recognized — try speaking closer to the microphone.",
                retryable=True,
            )

        return Transcript(text=text, detected_language=detect_language(text))

    def synthesize_reply(self, text: str, language: str) -> bytes | None:
        """Returns audio bytes, or None if TTS isn't configured or fails
        — callers should still show/use the text reply either way. This
        is the one place in the codebase where a provider failure is
        deliberately swallowed rather than raised, because losing the
        voice-out nicety shouldn't lose the whole response."""
        if self._tts is None:
            return None
        try:
            return self._tts.synthesize(text, language)
        except VoiceUnavailable:
            return None
