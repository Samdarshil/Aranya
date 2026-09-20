"""
Observability — spec section 28.

"AI systems are difficult to debug without observability... Make
agent/tool execution traceable." Real, minimal, stdlib-only: every agent
call the Orchestrator makes gets wrapped in `trace_agent_call`, which
measures duration and logs a single structured JSON line on exit —
success or failure, agent name, farm id, operation, duration in
milliseconds, and the error if one occurred. No external log
aggregation service is wired up (that would need network access this
sandbox doesn't have) — this produces the structured log lines a real
deployment would ship to one (CloudWatch, Datadog, ELK, whatever), via
whatever handler is attached to the "aranya" logger.

Deliberately does NOT change how any agent is called — `trace_agent_call`
wraps the call site in the Orchestrator, not the agent itself, so no
agent needed to change to get traced.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

LOGGER_NAME = "aranya"


def get_logger() -> logging.Logger:
    """Returns the shared Aranya logger, configuring a basic stdout
    handler exactly once if nothing has configured it yet. A real
    deployment can attach its own handler(s) to this logger name instead
    (or in addition) — this default just guarantees log lines go
    somewhere visible when nothing else is configured."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _log_agent_call(logger: logging.Logger, *, agent: str, farm_id: int, operation: str,
                     duration_ms: float, success: bool, error: str | None = None,
                     extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "agent_call",
        "agent": agent,
        "farm_id": farm_id,
        "operation": operation,
        "duration_ms": round(duration_ms, 2),
        "success": success,
    }
    if error is not None:
        payload["error"] = error
    if extra:
        payload.update(extra)
    logger.log(logging.INFO if success else logging.WARNING, json.dumps(payload))


class trace_agent_call:
    """Context manager: measures wall-clock duration of the wrapped block
    and logs a structured agent_call event on exit, whether the block
    succeeded or raised. Never suppresses the exception — observability
    should never change program behavior, only report on it.

    Usage:
        with trace_agent_call(farm_id, "vision_agent", "analyze_crop"):
            rec = self.vision_agent.analyze_crop(...)
    """

    def __init__(self, farm_id: int, agent: str, operation: str,
                 logger: logging.Logger | None = None):
        self.farm_id = farm_id
        self.agent = agent
        self.operation = operation
        self.logger = logger or get_logger()
        self._start: float = 0.0

    def __enter__(self) -> "trace_agent_call":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        duration_ms = (time.monotonic() - self._start) * 1000
        success = exc_type is None
        error = f"{exc_type.__name__}: {exc_val}" if exc_type is not None else None
        _log_agent_call(
            self.logger, agent=self.agent, farm_id=self.farm_id, operation=self.operation,
            duration_ms=duration_ms, success=success, error=error,
        )
        return False  # never suppress the exception
