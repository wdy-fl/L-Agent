from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


@dataclass
class ModelConfig:
    """Model configuration parameters."""

    model: str = "glm-5.2"
    temperature: float = 0.7
    max_tokens: int = 4096
    base_url: str = ""
    api_key: str = ""
    timeout: float = 120.0


@dataclass
class ModelRequest:
    """Iteration-level dynamic request, rebuilt every before_model."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Usage:
    """Token usage for a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StreamDelta:
    """A single streaming delta yielded during LLM streaming.

    Carries a ``kind`` discriminator so consumers can route reasoning vs.
    content deltas to different render paths.
    """

    kind: str  # "reasoning" | "content"
    text: str


@dataclass
class ModelResponse:
    """Response from an LLM call."""

    content: str = ""
    # 推理模型的思维链（GLM-5.2 等）。web_search 的检索引用也落在这里。
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    elapsed_ms: float = 0.0


class LLMClient(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def call(self, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    async def stream(
        self,
        request: ModelRequest,
    ) -> AsyncGenerator[StreamDelta | ModelResponse, None]:
        """Stream tokens, yielding StreamDelta for deltas and ModelResponse as the final item."""
        ...
