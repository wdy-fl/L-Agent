from __future__ import annotations

import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelResponse
from agent.steps.base import Step
from agent.timeline.models import Message


class MessageCommitAssistant(Step):
    """Commit assistant message (with or without tool_calls) to message list."""

    def __init__(self) -> None:
        super().__init__("message.commit_assistant", HookPhase.after_model)

    async def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        tool_calls_data = resp.tool_calls
        if tool_calls_data:
            ctx.messages.append({"role": "assistant", "content": resp.content, "tool_calls": tool_calls_data})
        else:
            ctx.messages.append({"role": "assistant", "content": resp.content})

        store = ctx.timeline_store
        if store is None:
            return
        seq = store.get_latest_sequence(ctx.branch_id) + 1
        msg = Message(
            message_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            sequence=seq,
            role="assistant",
            content=resp.content,
            tool_calls=tool_calls_data,
        )
        store.append_message(msg)
        return


class UsageUpdate(Step):
    """Accumulate token consumption into ctx.budget."""

    def __init__(self) -> None:
        super().__init__("usage.update", HookPhase.after_model)

    async def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return
        ctx.budget.consumed_input_tokens += resp.usage.input_tokens
        ctx.budget.consumed_output_tokens += resp.usage.output_tokens
        return


class ResultDetectRouting(Step):
    """Classify model response: final answer (no tool_calls) or tool request."""

    def __init__(self) -> None:
        super().__init__("result.detect_routing", HookPhase.after_model)

    async def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        if resp.tool_calls:
            ctx.has_tool_calls = True
        else:
            ctx.has_tool_calls = False
            ctx.final_result = resp.content
        return
