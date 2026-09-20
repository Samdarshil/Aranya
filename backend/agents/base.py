"""
Agent base class — spec section 8.

Every specialized agent (Vision, Weather, Soil, Market, ...) implements
this contract: a clear name, a declared set of tools/data it's allowed to
touch, and a `run` method that either returns a Recommendation or raises
AgentError with enough context for the orchestrator to decide what to do
next (retry, ask the farmer for more input, escalate).

Deterministic-vs-LLM note (spec section 8): this base class does not
assume an LLM is involved at all. VisionAgent below is fully
deterministic (classical CV + rule-based scoring) — no LLM call — which
is the correct choice per spec section 8 ("if a deterministic service is
better than an LLM agent, use a deterministic service").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from backend.core.schemas import Recommendation


class AgentError(Exception):
    """Raised when an agent cannot produce a safe recommendation.

    `retryable` tells the orchestrator whether asking again (e.g. with a
    better photo) could help, vs a hard failure that needs a different
    agent or human escalation.
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class AgentContext:
    """Everything an agent may need beyond its direct input — farm/field
    identity and a handle on Farm Memory for retrieving history. Agents
    must not reach outside this context (spec section 19: tool access
    boundaries)."""

    farm_id: int
    memory: Any  # backend.memory.store.FarmMemoryProtocol — Any to avoid a hard import cycle


class Agent(ABC):
    name: str = "base_agent"

    @abstractmethod
    def run(self, context: AgentContext, **kwargs: Any) -> Recommendation:
        """Execute the agent and return a structured Recommendation.
        Must raise AgentError rather than returning a low-confidence
        guess dressed up as a conclusion (spec section 15)."""
        raise NotImplementedError
