from __future__ import annotations

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelRequest
from agent.steps.base import Step


class IterationCreate(Step):
    """Increment iteration counter in ctx.budget."""

    def __init__(self) -> None:
        super().__init__("iteration.create", HookPhase.before_model)

    def run(self, ctx: RunContext) -> None:
        ctx.budget.consumed_iterations += 1

        return []


class ModelRequestCompose(Step):

    def __init__(self) -> None:
        super().__init__("model_request.compose", HookPhase.before_model)

    def run(self, ctx: RunContext) -> None:
        ctx.current_model_request = ModelRequest(
            messages=ctx.messages,
            tools=ctx.available_tools,
        )

        return []
