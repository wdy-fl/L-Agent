from __future__ import annotations

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelRequest
from agent.steps.base import Step


class BudgetGuard(Step):
    """Increment iteration counter and check budget limits before each model call."""

    def __init__(self) -> None:
        super().__init__("budget.guard", HookPhase.before_model)

    async def run(self, ctx: RunContext) -> None:
        budget = ctx.budget
        budget.consumed_iterations += 1
        if budget.consumed_iterations > budget.max_iterations:
            budget.exhausted = True
            return
        if budget.consumed_total_tokens >= budget.max_tokens:
            budget.exhausted = True
            return


class ModelRequestCompose(Step):

    def __init__(self) -> None:
        super().__init__("model_request.compose", HookPhase.before_model)

    async def run(self, ctx: RunContext) -> None:
        ctx.current_model_request = ModelRequest(
            messages=ctx.messages,
            tools=ctx.available_tools,
        )

        return
