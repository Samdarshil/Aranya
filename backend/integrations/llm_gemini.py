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
import time

import requests

from backend.core.llm_provider import LLMUnavailable

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4


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
        return cls(api_key=key, model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    generation_config = {"temperature": 0.2, "maxOutputTokens": 512}
                    if "ONLY a JSON object" in system_prompt:
                        generation_config["responseMimeType"] = "application/json"
                    resp = requests.post(
                        f"{BASE_URL}/{self._model}:generateContent",
                        headers={"x-goog-api-key": self._api_key},
                        json={
                            "systemInstruction": {"parts": [{"text": system_prompt}]},
                            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                            "generationConfig": generation_config,
                        },
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    if resp.status_code in {408, 429, 500, 502, 503, 504} and attempt < MAX_ATTEMPTS - 1:
                        time.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except requests.RequestException as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if attempt >= MAX_ATTEMPTS - 1 or (status is not None and status not in {408, 429, 500, 502, 503, 504}):
                        raise
                    time.sleep(2 ** attempt)
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Gemini request failed: {exc}") from exc

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Unexpected Gemini response shape: {exc}") from exc
