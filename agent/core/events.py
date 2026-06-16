from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agent.llm.client import ModelResponse


@dataclass(frozen=True)
class AgentEvent:
    """Base class for all agent events."""


# --- Run lifecycle ---


@dataclass(frozen=True)
class RunStart(AgentEvent):
    pass


@dataclass(frozen=True)
class RunDone(AgentEvent):
    status: str = ""
    result: Any = None


@dataclass(frozen=True)
class RunError(AgentEvent):
    error: Exception = field(default_factory=RuntimeError)


# --- Model ---


@dataclass(frozen=True)
class ModelStart(AgentEvent):
    pass


@dataclass(frozen=True)
class Token(AgentEvent):
    text: str = ""


@dataclass(frozen=True)
class ModelDone(AgentEvent):
    response: ModelResponse = field(default_factory=ModelResponse)


# --- Tool ---


@dataclass(frozen=True)
class ToolStart(AgentEvent):
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolDone(AgentEvent):
    tool_name: str = ""
    result: Any = None


# --- Approval ---


@dataclass(frozen=True)
class ApprovalRequest(AgentEvent):
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    risk_level: str = "low"
    future: asyncio.Future = field(default=None, compare=False, hash=False)  # type: ignore[assignment]
