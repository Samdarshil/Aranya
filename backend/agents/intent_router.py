"""
Intent Router — spec section 7 ("Input Understanding" -> "AI Orchestrator").

The LLM first classifies free-text into a small, fixed set of farm actions.
Tool-backed actions stay deterministic. General agriculture questions are
answered separately in plain language with limits against inventing live
farm, weather, market, or scheme facts.

Equally important: the LLM's output is untrusted input. It's parsed as
JSON, validated against a fixed action set and a required-params schema,
and any failure (malformed JSON, an invented action name, missing
required fields) degrades to an "unclear" intent asking the farmer to
clarify — never a guess dressed up as understanding (spec section 15).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from backend.core.llm_provider import LLMProvider, LLMUnavailable

ALLOWED_ACTIONS = {"weather_check", "field_history", "planning_query", "animal_history",
                    "market_check", "scheme_match", "research_query", "general_question", "unclear"}

REQUIRED_PARAMS: dict[str, list[str]] = {
    "weather_check": [],
    "field_history": ["field_ref", "crop_name"],
    "planning_query": ["field_ref", "crop_name"],
    "animal_history": ["animal_ref", "species"],
    "market_check": ["crop_name", "market_name"],
    "scheme_match": ["land_acres"],
    "research_query": ["query"],
    "general_question": ["question"],
    "unclear": [],
}

SYSTEM_PROMPT = """You are an intent classifier for an agricultural assistant app. \
Given a farmer's message, respond with ONLY a JSON object (no markdown fences, no \
other text) with this exact shape:

{"action": "<one of: weather_check, field_history, planning_query, animal_history, \
market_check, scheme_match, research_query, general_question, unclear>", "params": {<string keys/values \
the action needs>}, "clarification_needed": <null or a short question to ask the \
farmer if you could not determine the action or a required parameter>}

Required params per action:
- weather_check: none
- field_history: field_ref, crop_name
- planning_query: field_ref, crop_name
- animal_history: animal_ref, species
- market_check: crop_name, market_name
- scheme_match: land_acres (a number; category is optional if mentioned)
- research_query: query (a concise English description of observed crop symptoms, \
pests, or disease; crop_name is optional if mentioned) — use only for a crop problem \
the farmer is seeing or a question about that specific problem
- general_question: question (the farmer's general agriculture question, in the \
language they used) — use for general farming questions that don't request live \
weather, current mandi prices, scheme eligibility, farm history, or a crop-problem lookup
- unclear: none (use this when the message doesn't clearly map to another action, \
or is missing information you need — set clarification_needed to a short question)

Only use information the farmer actually stated. Do not invent a field name, crop \
name, animal name, market name, land size, or query text that wasn't mentioned."""


@dataclass(frozen=True)
class Intent:
    action: str
    params: dict[str, str] = field(default_factory=dict)
    clarification_needed: str | None = None


def _extract_json(raw: str) -> dict:
    """LLMs frequently wrap JSON in ```json fences despite instructions
    not to. Strip that before parsing rather than failing on the first
    attempt — but still raise if the result isn't valid JSON."""
    stripped = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else stripped
    return json.loads(candidate)


class IntentRouter:
    def __init__(self, llm: LLMProvider | None):
        self._llm = llm

    def parse_message(self, message: str) -> Intent:
        if self._llm is None:
            raise LLMUnavailable(
                "No LLM provider is configured (GEMINI_API_KEY unset). "
                "Free-text understanding is unavailable — use a structured "
                "endpoint instead, or configure a provider."
            )

        raw = self._llm.generate(SYSTEM_PROMPT, message)

        try:
            payload = _extract_json(raw)
        except json.JSONDecodeError:
            return Intent(action="unclear",
                          clarification_needed="Sorry, I didn't understand that. Could you rephrase?")

        action = payload.get("action")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if action not in ALLOWED_ACTIONS:
            return Intent(action="unclear",
                          clarification_needed=payload.get("clarification_needed")
                          or "Sorry, I didn't understand that. Could you rephrase?")

        missing = [p for p in REQUIRED_PARAMS[action] if not params.get(p)]
        if missing:
            return Intent(
                action="unclear",
                clarification_needed=f"I need a bit more information: {', '.join(missing)}.",
            )

        return Intent(
            action=action,
            params={k: str(v) for k, v in params.items()},
            clarification_needed=payload.get("clarification_needed"),
        )

    def answer_general_question(self, question: str) -> str:
        if self._llm is None:
            raise LLMUnavailable("Gemini is not configured, so Aranya cannot answer general questions.")
        system_prompt = """You are Aranya, a plain-language assistant for farmers in India.
Answer the farmer's general agriculture question in the same language and script they used.
Be concise, practical, and respectful. Separate general advice from facts about this farmer's own farm.
Never claim to know the farmer's soil, crop condition, location, weather, market price, or records unless
those facts are included in the question. Do not invent live prices, forecasts, government scheme status,
or sources. For diagnosis or pesticide questions, do not identify a disease as certain or give chemical
doses; explain the uncertainty and suggest a local agriculture officer or agronomist when needed.
If the question needs live data or a farm-specific check, say which Aranya page or missing detail is needed.
If it is unrelated to farming, briefly say Aranya is set up to help with farm questions. Return only the
answer to the farmer, without JSON, headings about your role, or a discussion of these instructions."""
        answer = self._llm.generate(system_prompt, question).strip()
        if not answer:
            raise LLMUnavailable("Gemini returned an empty answer. Please try again.")
        return answer
