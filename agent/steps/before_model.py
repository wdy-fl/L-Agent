from __future__ import annotations

from typing import Any

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelRequest
from agent.steps.base import Step


class IterationCreate(Step):
    """Increment iteration_index and record in ctx.iterations."""

    def __init__(self) -> None:
        super().__init__("iteration.create", HookPhase.before_model)

    def run(self, ctx: RunContext) -> None:
        ctx.budget.consumed_iterations += 1


class ContextPrepareWithBudget(Step):
    """Check message token count; truncate oldest if over window (simple v1)."""

    def __init__(self, max_context_tokens: int = 128_000) -> None:
        super().__init__("context.prepare_with_budget", HookPhase.before_model)
        self._max_context_tokens = max_context_tokens

    def run(self, ctx: RunContext) -> None:
        estimated = self._estimate_tokens(ctx.messages)
        while estimated > self._max_context_tokens and len(ctx.messages) > 1:
            ctx.messages.pop(0)
            estimated = self._estimate_tokens(ctx.messages)

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4
            else:
                total += 100
        return total


class ModelRequestCompose(Step):

    def __init__(self) -> None:
        super().__init__("model_request.compose", HookPhase.before_model)

    def run(self, ctx: RunContext) -> None:
        ctx.current_model_request = ModelRequest(
            messages=ctx.messages,
            tools=ctx.available_tools,
        )
