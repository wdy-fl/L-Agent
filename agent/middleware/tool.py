from __future__ import annotations

from typing import Any, Callable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName
from agent.middleware.base import Middleware
from agent.tools.base import ToolResult


class ApprovalGuard(Middleware):
    """Approval is handled by AgentRunner's event loop; this middleware is a no-op passthrough."""

    def __init__(self) -> None:
        super().__init__("approval.guard", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        return next_call()


class AuditRecord(Middleware):
    """Record tool execution timing and metadata."""

    def __init__(self) -> None:
        super().__init__("audit.record", ActionName.tool_call)

    def __call__(self, ctx: RunContext, next_call: Callable[[], Any]) -> Any:
        return next_call()


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
