"""
Gemini provider — a real implementation of LLMProvider.

STATUS: written, NOT executed in the authoring sandbox — no network
access there to call the live Gemini API. The request/response shape
below is standard for Gemini's generateContent REST endpoint; verify
against a real API key on a machine with network access. The logic that
CONSUMES this provider's output (IntentRouter's JSON parsing/validation)
IS tested, via a fake provider — see tests/test_intent_router.py.
"""

from __future__ import annotations

import os

import requests

from backend.core.llm_provider import LLMUnavailable

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-1.5-flash"
REQUEST_TIMEOUT_SECONDS = 30


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_env(cls) -> "GeminiProvider | None":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            resp = requests.post(
                f"{BASE_URL}/{self._model}:generateContent",
                params={"key": self._api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Gemini request failed: {exc}") from exc

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Unexpected Gemini response shape: {exc}") from exc
