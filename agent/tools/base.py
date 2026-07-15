from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ToolResultStatus(str, Enum):
    success = "success"
    error = "error"
    denied = "denied"


@dataclass
class ToolSpec:
    """Definition of a tool available to the agent."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Any]


@dataclass
class ToolCall:
    """A parsed tool call from the model response."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ToolResult:
    """Result of a tool execution."""

    call_id: str
    tool_name: str = ""
    status: ToolResultStatus = ToolResultStatus.success
    content: str = ""


