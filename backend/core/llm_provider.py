"""
LLM provider abstraction — spec section 6.

"The architecture should support Gemini or other cloud LLMs... Do not
tightly couple the entire system to a single model provider." Same
Protocol + honest-unavailability pattern as backend/core/providers.py's
WeatherProvider — an agent that needs an LLM depends on this interface,
never on a specific vendor's SDK.
"""

from __future__ import annotations

from typing import Protocol


class LLMUnavailable(Exception):
    """Raised when no LLM call can be completed — no provider configured,
    network failure, or the provider returned something unusable. Callers
    must treat this as 'cannot understand free text right now', never
    fall back to guessing what the farmer meant."""


class LLMProvider(Protocol):
    name: str

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Returns the raw text completion. Raises LLMUnavailable on any
        failure. Callers that need structured output are responsible for
        prompting for and parsing JSON themselves (see IntentRouter) —
        this Protocol stays at the lowest common denominator so it works
        with any provider's raw completion endpoint."""
        ...
