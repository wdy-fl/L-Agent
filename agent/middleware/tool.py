from __future__ import annotations

import time
from typing import Any, Callable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName
from agent.middleware.base import Middleware
from agent.tools.base import ToolResult


class ApprovalGuard(Middleware):
    """Approval is handled by AgentRunner via ctx.request_approval; this middleware is a no-op passthrough."""

    def __init__(self) -> None:
        super().__init__("approval.guard", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        return next_call()


class AuditRecord(Middleware):
    """Record tool execution timing and metadata."""

    def __init__(self) -> None:
        super().__init__("audit.record", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        if ctx.logger is None:
            return next_call()

        t0 = time.time()

        # Build a lookup: call_id -> tool_name for matching results
        call_id_to_name: dict[str, str] = {}
        calls = ctx.current_tool_calls
        if calls:
            for tc in calls:
                call_id_to_name[tc.call_id] = tc.tool_name
                ctx.logger.log(
                    event="tool.start",
                    run_id=ctx.run_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )

        result = next_call()

        elapsed_ms = (time.time() - t0) * 1000
        if isinstance(result, list):
            for r in result:
                if isinstance(r, ToolResult):
                    tool_name = call_id_to_name.get(r.call_id, r.call_id)
                    ctx.logger.log(
                        event="tool.done",
                        run_id=ctx.run_id,
                        tool_name=tool_name,
                        elapsed_ms=round(elapsed_ms, 1),
                        status=r.status.value,
                        result=r.content,
                    )
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
