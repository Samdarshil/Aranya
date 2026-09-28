"""Groq Whisper speech-to-text provider for browser-recorded audio."""

from __future__ import annotations

import os

import requests

from backend.core.voice_provider import VoiceUnavailable

TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3"
REQUEST_TIMEOUT_SECONDS = 60


def _audio_file_details(audio_bytes: bytes) -> tuple[str, str]:
    """Give Groq a useful filename and MIME type for common phone recordings."""
    if audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE":
        return "recording.wav", "audio/wav"
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "recording.webm", "audio/webm"
    if audio_bytes.startswith(b"OggS"):
        return "recording.ogg", "audio/ogg"
    if audio_bytes.startswith(b"fLaC"):
        return "recording.flac", "audio/flac"
    if audio_bytes.startswith(b"ID3") or (
        len(audio_bytes) > 1 and audio_bytes[0] == 0xFF and audio_bytes[1] & 0xE0 == 0xE0
    ):
        return "recording.mp3", "audio/mpeg"
    if len(audio_bytes) > 8 and audio_bytes[4:8] == b"ftyp":
        return "recording.m4a", "audio/mp4"
    # Browser capture on Android commonly produces WebM; Groq accepts it.
    return "recording.webm", "audio/webm"


class GroqSpeechProvider:
    """Transcribe uploaded audio with Groq's multilingual Whisper model."""

    name = "groq_whisper"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_env(cls) -> "GroqSpeechProvider | None":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            return None
        return cls(api_key=key, model=os.environ.get("GROQ_STT_MODEL", DEFAULT_MODEL))

    def transcribe(self, audio_bytes: bytes, language_hint: str | None = None) -> str:
        filename, mime_type = _audio_file_details(audio_bytes)
        data = {"model": self._model, "response_format": "json", "temperature": "0"}
        if language_hint in {"hi", "en"}:
            data["language"] = language_hint

        try:
            response = requests.post(
                TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data=data,
                files={"file": (filename, audio_bytes, mime_type)},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status:
                raise VoiceUnavailable(
                    f"Groq transcription request failed (HTTP {status}). Check the key, quota, and audio format."
                ) from exc
            raise VoiceUnavailable("Groq transcription service did not respond. Please try again.") from exc
        except ValueError as exc:
            raise VoiceUnavailable("Groq returned an unreadable transcription response.") from exc

        transcript = result.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            raise VoiceUnavailable("Groq did not recognize speech in this recording.")
        return transcript.strip()
