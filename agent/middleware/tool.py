from __future__ import annotations

import time
from typing import Any, Callable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName
from agent.middleware.base import Middleware
from agent.tools.base import ToolPlan, ToolResult


class ApprovalGuard(Middleware):
    """Check if tool calls need approval; generate denied results if rejected."""

    def __init__(self) -> None:
        super().__init__("approval.guard", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        plan: ToolPlan | None = ctx.current_tool_plan
        if plan is None:
            return next_call()

        denied_results: list[ToolResult] = []
        remaining_calls = []

        for call in plan.calls:
            if call.error:
                remaining_calls.append(call)
                continue
            remaining_calls.append(call)

        plan.calls = remaining_calls
        if denied_results:
            results = next_call()
            if isinstance(results, list):
                return denied_results + results
            return denied_results

        return next_call()


class AuditRecord(Middleware):
    """Record tool execution timing and metadata."""

    def __init__(self) -> None:
        super().__init__("audit.record", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        start = time.time()
        result = next_call()
        elapsed = time.time() - start

        if ctx.iterations:
            current = ctx.iterations[-1]
            current["tool_call_duration_ms"] = int(elapsed * 1000)

        return result


class ResultLimitGuard(Middleware):
    """Truncate tool results that exceed the size limit."""

    def __init__(self, max_chars: int = 50_000) -> None:
        super().__init__("result_limit.guard", ActionName.tool_call)
        self._max_chars = max_chars

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        results = next_call()
        if not isinstance(results, list):
            return results

        for result in results:
            if isinstance(result, ToolResult) and len(result.content) > self._max_chars:
                result.content = (
                    result.content[: self._max_chars]
                    + f"\n\n[Truncated: result exceeded {self._max_chars} characters]"
                )

        return results
