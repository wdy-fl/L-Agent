from __future__ import annotations

import time
from typing import Any, Callable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName
from agent.llm.client import ModelResponse
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
        if ctx.logger is None:
            return next_call()

        t0 = time.time()
        req = ctx.current_model_request
        ctx.logger.log(
            event="model.start",
            run_id=ctx.run_id,
            iteration=ctx.budget.consumed_iterations,
            messages_count=len(req.messages) if req else 0,
            tools_count=len(req.tools) if req else 0,
        )

        result = next_call()

        elapsed_ms = (time.time() - t0) * 1000
        response = result if isinstance(result, ModelResponse) else None
        ctx.logger.log(
            event="model.done",
            run_id=ctx.run_id,
            iteration=ctx.budget.consumed_iterations,
            elapsed_ms=round(elapsed_ms, 1),
            tokens_in=response.usage.input_tokens if response else 0,
            tokens_out=response.usage.output_tokens if response else 0,
            finish_reason=response.finish_reason if response else "",
            content=response.content if response else str(result),
            reasoning_content=response.reasoning_content if response else "",
            tool_calls=[
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in (response.tool_calls if response else [])
            ],
        )
        return result
