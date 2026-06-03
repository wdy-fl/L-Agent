from __future__ import annotations

import time
from typing import Any, Callable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName
from agent.middleware.base import Middleware


class BudgetGuard(Middleware):
    """Check ReAct max iterations / token budget before model call."""

    def __init__(self) -> None:
        super().__init__("budget.guard", ActionName.model_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        budget = ctx.budget
        if budget.consumed_iterations > budget.max_iterations:
            budget.exhausted = True
            ctx.interrupted = True
            return None
        if budget.consumed_total_tokens >= budget.max_tokens:
            budget.exhausted = True
            ctx.interrupted = True
            return None
        return next_call()


class TimeoutGuard(Middleware):
    """Control model call timeout."""

    def __init__(self, timeout_seconds: float = 120.0) -> None:
        super().__init__("timeout.guard", ActionName.model_call)
        self._timeout = timeout_seconds

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        start = time.time()
        result = next_call()
        elapsed = time.time() - start
        if elapsed > self._timeout:
            raise TimeoutError(
                f"Model call exceeded timeout: {elapsed:.1f}s > {self._timeout:.1f}s"
            )
        return result


class TraceRecord(Middleware):
    """Record model call timing and usage metadata."""

    def __init__(self) -> None:
        super().__init__("trace.record", ActionName.model_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        start = time.time()
        result = next_call()
        elapsed = time.time() - start

        if ctx.iterations:
            current = ctx.iterations[-1]
            current["model_call_duration_ms"] = int(elapsed * 1000)
            if result and hasattr(result, "usage"):
                current["usage"] = {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                }

        return result
