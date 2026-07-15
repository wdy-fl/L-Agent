from __future__ import annotations

import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.steps.base import Step
from agent.timeline.models import Checkpoint, CheckpointType, Message
from agent.tools.base import ToolResult, ToolResultStatus


class ToolDoneLogging(Step):
    """Log tool.done events with elapsed time for each tool result."""

    def __init__(self) -> None:
        super().__init__("tools.done_logging", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
        results = ctx.current_tool_results
        if not results or not isinstance(results, list):
            return

        # Build call_id→tool_name lookup from the (possibly filtered) tool calls
        call_id_to_name: dict[str, str] = {}
        for tc in ctx.current_tool_calls or []:
            call_id_to_name[tc.call_id] = tc.tool_name

        from agent.logging import get_logger

        logger = get_logger()
        for r in results:
            if isinstance(r, ToolResult):
                tool_name = call_id_to_name.get(r.call_id, r.call_id)
                logger.log(
                    event="tool.done",
                    run_id=ctx.run_id,
                    tool_name=tool_name,
                    status=r.status.value,
                    result=r.content,
                )


class ResultLimitGuard(Step):
    """Truncate tool results that exceed 50,000 characters."""

    def __init__(self) -> None:
        super().__init__("result.limit_guard", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
        results = ctx.current_tool_results
        if not isinstance(results, list):
            return

        for result in results:
            if isinstance(result, ToolResult) and len(result.content) > 50_000:
                result.content = (
                    result.content[:50_000]
                    + f"\n\n[Truncated: result exceeded 50_000 characters]"
                )


class ToolResultsRender(Step):
    """Render tool results via ctx.renderer.finish_tool()."""

    def __init__(self) -> None:
        super().__init__("tools.render", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
        renderer = ctx.renderer
        if renderer is None:
            return

        results = ctx.current_tool_results
        for result in results:
            renderer.finish_tool(
                getattr(result, "tool_name", ""),
                getattr(result, "content", str(result)),
            )


class ToolResultsCapture(Step):
    """Collect execution results into ctx.current_tool_results."""

    def __init__(self) -> None:
        super().__init__("tool_results.capture", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
        return


class MessageCommitToolResults(Step):
    """Commit tool results as role=tool messages to the message list."""

    def __init__(self) -> None:
        super().__init__("message.commit_tool_results", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
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

            store = ctx.timeline_store
            if store is None:
                continue
            seq = store.get_latest_sequence(ctx.branch_id) + 1
            msg = Message(
                message_id=str(uuid.uuid4()),
                session_id=ctx.session_id,
                branch_id=ctx.branch_id,
                run_id=ctx.run_id,
                sequence=seq,
                role="tool",
                content=content,
                tool_call_id=result.call_id,
            )
            store.append_message(msg)

        return


class CheckpointRecordToolResultsCommitted(Step):
    """Create runtime checkpoint after tool results are committed."""

    def __init__(self) -> None:
        super().__init__("checkpoint.record_tool_results_committed", HookPhase.after_tool)

    async def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        cursor = store.get_latest_sequence(ctx.branch_id)
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            type=CheckpointType.runtime,
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)

        return
