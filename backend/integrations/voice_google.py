"""
Google Cloud Speech provider — real implementations of
SpeechToTextProvider and TextToSpeechProvider.

STATUS: written, NOT executed in the authoring sandbox — no network
access there to call Google Cloud's Speech-to-Text or Text-to-Speech
REST APIs, and no way to test actual audio I/O in a sandboxed text-only
environment even if network were available. The request/response shape
below matches Google Cloud Speech's standard REST API v1 conventions;
verify against real credentials and real audio on a machine with network
access and a way to produce/play audio. Unlike the other providers in
this codebase (weather, market, LLM), there is no meaningful way to
sanity-check this one's core behavior without actual audio hardware/files
— what IS tested is everything downstream of it (VoiceAgent's
orchestration logic, via a fake provider — see tests/test_voice_agent.py).

Requires the `google-cloud-speech` and `google-cloud-texttospeech`
packages and a service account credentials file — not listed in
requirements.txt by default since this is optional/unverified; add them
if you wire this in for real.
"""

from __future__ import annotations

import base64
import os

import requests

from backend.core.voice_provider import VoiceUnavailable

STT_URL = "https://speech.googleapis.com/v1/speech:recognize"
TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
REQUEST_TIMEOUT_SECONDS = 30

# Google Cloud Speech language codes for the two scripts this project's
# language_detection module distinguishes. A real deployment supporting
# more Indian languages would extend this mapping.
_LANGUAGE_CODES = {"hi": "hi-IN", "en": "en-IN", "mixed": "hi-IN"}


class GoogleSpeechProvider:
    """Implements both SpeechToTextProvider and TextToSpeechProvider —
    Google Cloud Speech covers both under one API family/credential."""

    name = "google_cloud_speech"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "GoogleSpeechProvider | None":
        key = os.environ.get("GOOGLE_SPEECH_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def transcribe(self, audio_bytes: bytes, language_hint: str | None = None) -> str:
        language_code = _LANGUAGE_CODES.get(language_hint or "hi", "hi-IN")
        try:
            resp = requests.post(
                STT_URL,
                params={"key": self._api_key},
                json={
                    "config": {
                        "encoding": "LINEAR16",
                        "sampleRateHertz": 16000,
                        "languageCode": language_code,
                        "alternativeLanguageCodes": list(_LANGUAGE_CODES.values()),
                    },
                    "audio": {"content": base64.b64encode(audio_bytes).decode("ascii")},
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise VoiceUnavailable(f"Speech-to-text request failed: {exc}") from exc

        results = data.get("results") or []
        if not results:
            raise VoiceUnavailable("No speech was recognized in the audio.")
        try:
            return results[0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError) as exc:
            raise VoiceUnavailable(f"Unexpected speech-to-text response shape: {exc}") from exc

    def synthesize(self, text: str, language: str) -> bytes:
        language_code = _LANGUAGE_CODES.get(language, "en-IN")
        try:
            resp = requests.post(
                TTS_URL,
                params={"key": self._api_key},
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": language_code, "ssmlGender": "NEUTRAL"},
                    "audioConfig": {"audioEncoding": "MP3"},
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise VoiceUnavailable(f"Text-to-speech request failed: {exc}") from exc

        try:
            return base64.b64decode(data["audioContent"])
        except (KeyError, ValueError) as exc:
            raise VoiceUnavailable(f"Unexpected text-to-speech response shape: {exc}") from exc
