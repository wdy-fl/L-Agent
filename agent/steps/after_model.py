from __future__ import annotations

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.types import ModelResponse
from agent.steps.base import Step


class ModelCaptureResponse(Step):
    """Write raw model response into ctx.current_model_response."""

    def __init__(self) -> None:
        super().__init__("model.capture_response", HookPhase.after_model)

    def run(self, ctx: RunContext) -> None:
        pass


class MessageCommitAssistant(Step):
    """Commit assistant message (with or without tool_calls) to message list."""

    def __init__(self) -> None:
        super().__init__("message.commit_assistant", HookPhase.after_model)

    def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        if resp.tool_calls:
            ctx.messages.append({
                "role": "assistant",
                "content": resp.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in resp.tool_calls
                ],
            })
        else:
            ctx.messages.append({"role": "assistant", "content": resp.content})


class UsageUpdate(Step):
    """Accumulate token consumption into ctx.budget."""

    def __init__(self) -> None:
        super().__init__("usage.update", HookPhase.after_model)

    def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return
        ctx.budget.consumed_input_tokens += resp.usage.input_tokens
        ctx.budget.consumed_output_tokens += resp.usage.output_tokens


class ResultDetectFinalAnswer(Step):
    """If model has no tool_calls, set ctx.final_result."""

    def __init__(self) -> None:
        super().__init__("result.detect_final_answer", HookPhase.after_model)

    def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        if not resp.tool_calls:
            ctx.has_tool_calls = False
            ctx.final_result = resp.content


class ToolDetectRequested(Step):
    """If model response has tool_calls, set ctx.has_tool_calls = True."""

    def __init__(self) -> None:
        super().__init__("tool.detect_requested", HookPhase.after_model)

    def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        if resp.tool_calls:
            ctx.has_tool_calls = True
