from __future__ import annotations

from agent.tools.base import ToolCall, ToolResult, ToolResultStatus
from agent.tools.registry import ToolRegistry


class ToolDispatcher:
    """Executes tool calls serially with defensive validation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def dispatch(self, calls: list[ToolCall]) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            result = self._execute_single(call)
            results.append(result)
        return results

    def _execute_single(self, call: ToolCall) -> ToolResult:
        if call.error:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolResultStatus.error,
                content=call.error,
            )

        spec = self._registry.get(call.tool_name)
        if spec is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolResultStatus.error,
                content=f"Tool not found: {call.tool_name}",
            )

        try:
            result = spec.handler(**call.arguments)
            content = str(result) if result is not None else ""
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolResultStatus.success,
                content=content,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolResultStatus.error,
                content=f"Tool execution error: {type(exc).__name__}: {exc}",
            )
