from __future__ import annotations

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.steps.base import Step
from agent.tools.base import ToolResult, ToolResultStatus


class ToolResultsCapture(Step):
    """Collect execution results into ctx.current_tool_results."""

    def __init__(self) -> None:
        super().__init__("tool_results.capture", HookPhase.after_tool)

    def run(self, ctx: RunContext) -> None:
        pass


class MessageCommitToolResults(Step):
    """Commit tool results as role=tool messages to the message list."""

    def __init__(self) -> None:
        super().__init__("message.commit_tool_results", HookPhase.after_tool)

    def run(self, ctx: RunContext) -> None:
        results = ctx.current_tool_results
        if not results or not isinstance(results, list):
            return

        for result in results:
            if not isinstance(result, ToolResult):
                continue

            content = result.content
            if result.status == ToolResultStatus.denied:
                content = f"[DENIED] {content}"
            elif result.status == ToolResultStatus.error:
                content = f"[ERROR] {content}"

            ctx.messages.append({
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": content,
            })
