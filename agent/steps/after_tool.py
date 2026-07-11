from __future__ import annotations

from typing import Any
import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.steps.base import Step
from agent.timeline.models import Checkpoint, CheckpointType, Message
from agent.tools.base import ToolResult, ToolResultStatus


class ToolResultsCapture(Step):
    """Collect execution results into ctx.current_tool_results."""

    def __init__(self) -> None:
        super().__init__("tool_results.capture", HookPhase.after_tool)

    def run(self, ctx: RunContext) -> list[Any]:
        return []


class MessageCommitToolResults(Step):
    """Commit tool results as role=tool messages to the message list."""

    def __init__(self) -> None:
        super().__init__("message.commit_tool_results", HookPhase.after_tool)

    def run(self, ctx: RunContext) -> list[Any]:
        results = ctx.current_tool_results
        if not results or not isinstance(results, list):
            return []

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

        return []


class CheckpointRecordToolResultsCommitted(Step):
    """Create runtime checkpoint after tool results are committed."""

    def __init__(self) -> None:
        super().__init__("checkpoint.record_tool_results_committed", HookPhase.after_tool)

    def run(self, ctx: RunContext) -> list[Any]:
        store = ctx.timeline_store
        if store is None:
            return []
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

        return []
