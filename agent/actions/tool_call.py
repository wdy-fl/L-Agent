from __future__ import annotations

from agent.core.context import RunContext
from agent.tools.base import ToolCall, ToolResult
from agent.tools.dispatcher import ToolDispatcher


def make_tool_call_action(dispatcher: ToolDispatcher):
    """Create a tool_call action that uses the given ToolDispatcher."""

    def tool_call(ctx: RunContext) -> list[ToolResult]:
        calls: list[ToolCall] | None = ctx.current_tool_plan
        if calls is None:
            return []
        return dispatcher.dispatch(calls)

    return tool_call
