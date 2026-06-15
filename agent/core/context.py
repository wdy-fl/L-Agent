from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.timeline.store import TimelineStore


@dataclass
class ModelConfig:
    """Model configuration parameters."""

    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    api_base: str = ""
    api_key: str = ""


@dataclass
class ModelRequest:
    """Iteration-level dynamic request, rebuilt every before_model."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class ToolCallRequest:
    """A single tool call within a model response."""

    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class Usage:
    """Token usage for a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelResponse:
    """Response from an LLM call."""

    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


@dataclass
class BudgetState:
    """Tracks budget consumption for the current run."""

    max_iterations: int = 25
    max_tokens: int = 200_000
    consumed_iterations: int = 0
    consumed_input_tokens: int = 0
    consumed_output_tokens: int = 0
    exhausted: bool = False

    @property
    def consumed_total_tokens(self) -> int:
        return self.consumed_input_tokens + self.consumed_output_tokens


@dataclass
class RunContext:
    """Mutable blackboard for a single AgentRun."""

    # --- timeline ---
    session_id: str = ""
    branch_id: str = ""
    run_id: str = ""

    errors: list[Exception] = field(default_factory=list)
    interrupted: bool = False

    # --- messages ---
    input: str = ""
    enhanced_input: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)

    # --- model context ---
    model_config: ModelConfig = field(default_factory=ModelConfig)
    current_model_request: ModelRequest | None = None
    current_model_response: ModelResponse | None = None

    # --- tool context---
    available_tools: list[dict[str, Any]] = field(default_factory=list)
    current_tool_plan: Any = None
    current_tool_results: Any = None
    has_tool_calls: bool = False
    auto_approve_tools: set[str] = field(default_factory=set)
    always_confirm_tools: set[str] = field(default_factory=set)

    # --- budget ---
    budget: BudgetState = field(default_factory=BudgetState)

    # --- result ---
    final_result: Any = None
    status: str = "running"

    # --- timeline store ---
    timeline_store: TimelineStore | None = None
