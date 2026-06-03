from __future__ import annotations

import uuid

from agent.core.context import BudgetState, RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.types import BaseModelContext, ModelConfig
from agent.steps.base import Step
from agent.tools.registry import ToolRegistry


class ContextInitialize(Step):
    """Create RunContext basic fields, initialize empty iterations list."""

    def __init__(self) -> None:
        super().__init__("context.initialize", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        if not ctx.run_id:
            ctx.run_id = str(uuid.uuid4())
        ctx.iterations = []
        ctx.iteration_index = 0
        ctx.status = "running"


class InputNormalize(Step):
    """Normalize user input: strip whitespace, record raw input."""

    def __init__(self) -> None:
        super().__init__("input.normalize", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        ctx.raw_input = ctx.input
        ctx.input = ctx.input.strip()


class BaseContextLoadStaticParts(Step):
    """Load identity / guidance / workspace into ctx.base_model_context."""

    def __init__(
        self,
        identity: str = "",
        guidance: str = "",
        workspace_context: str = "",
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__("base_context.load_static_parts", HookPhase.before_agent)
        self._identity = identity
        self._guidance = guidance
        self._workspace_context = workspace_context
        self._model_config = model_config or ModelConfig()

    def run(self, ctx: RunContext) -> None:
        ctx.base_model_context = BaseModelContext(
            identity=self._identity,
            guidance=self._guidance,
            workspace_context=self._workspace_context,
            model_config=self._model_config,
        )


class MemoryPrefetch(Step):
    """Placeholder: memory prefetch (real logic in a later step)."""

    def __init__(self) -> None:
        super().__init__("memory.prefetch", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        if ctx.base_model_context:
            ctx.base_model_context.memory_context = None


class ToolsSnapshotAvailableTools(Step):
    """Snapshot available tools from ToolRegistry into ctx.base_model_context."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        super().__init__("tools.snapshot_available_tools", HookPhase.before_agent)
        self._registry = registry

    def run(self, ctx: RunContext) -> None:
        if ctx.base_model_context is None:
            return
        if self._registry is None:
            ctx.base_model_context.available_tools = []
        else:
            ctx.base_model_context.available_tools = self._registry.list_schemas()


class BudgetInitialize(Step):
    """Initialize budget state (max iterations, token limits)."""

    def __init__(
        self,
        max_iterations: int = 25,
        max_tokens: int = 200_000,
    ) -> None:
        super().__init__("budget.initialize", HookPhase.before_agent)
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens

    def run(self, ctx: RunContext) -> None:
        ctx.budget = BudgetState(
            max_iterations=self._max_iterations,
            max_tokens=self._max_tokens,
        )
