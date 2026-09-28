"""
Voice I/O provider abstraction — spec section 16.

Same Protocol + honest-unavailability pattern as backend/core/providers.py
and backend/core/llm_provider.py. No agent is hardwired to one vendor's
speech API.
"""

from __future__ import annotations

from typing import Protocol


class VoiceUnavailable(Exception):
    """Raised when STT/TTS cannot be completed — no provider configured,
    network failure, unrecognized audio, or unsupported language.
    Callers must treat this as 'voice unavailable', never fabricate a
    transcript or synthesized reply."""


class SpeechToTextProvider(Protocol):
    name: str

    def transcribe(self, audio_bytes: bytes, language_hint: str | None = None) -> str:
        """Returns the transcribed text. Raises VoiceUnavailable on any
        failure. `language_hint` is an optional ISO code (e.g. "hi", "en")
        to bias recognition — providers that don't support hinting can
        ignore it."""
        ...


class TextToSpeechProvider(Protocol):
    name: str

    def synthesize(self, text: str, language: str) -> bytes:
        """Returns synthesized audio bytes for `text` in `language`
        (ISO code). Raises VoiceUnavailable on any failure, including an
        unsupported language."""
        ...
