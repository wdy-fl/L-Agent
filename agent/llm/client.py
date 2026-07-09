from __future__ import annotations

from dataclasses import dataclass, field
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

import httpx


@dataclass
class ModelConfig:
    """Model configuration parameters."""

    model: str = "glm-5.2"
    temperature: float = 0.7
    max_tokens: int = 4096
    api_base: str = ""
    api_key: str = ""
    timeout: float = 120.0


@dataclass
class ModelRequest:
    """Iteration-level dynamic request, rebuilt every before_model."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)


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
    # 推理模型的思维链（GLM-5.2 等）。web_search 的检索引用也落在这里。
    reasoning_content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


class LLMClient(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def call(self, request: ModelRequest) -> ModelResponse: ...

    async def stream(self, request: ModelRequest) -> AsyncGenerator[str | ModelResponse, None]:
        """Stream tokens, yielding str for deltas and ModelResponse as the final item."""
        yield self.call(request)


class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible client (supports DeepSeek, GPT, Claude-compatible endpoints)."""

    def __init__(self, config: ModelConfig) -> None:
        self._api_base = config.api_base.rstrip("/")
        self._api_key = config.api_key
        self._timeout = config.timeout
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    def call(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request)
        headers = self._headers()

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._api_base}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        return self._parse_response(resp.json())

    async def stream(self, request: ModelRequest) -> AsyncGenerator[str | ModelResponse, None]:
        payload = self._build_payload(request)
        payload["stream"] = True

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_raw: dict[int, dict] = {}
        usage_data: dict = {}
        finish_reason = "stop"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._api_base}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})

                    if text := delta.get("content"):
                        content_parts.append(text)
                        yield text

                    # 推理模型的思维链（不实时吐给前端，仅在最终响应里带回）。
                    if rc := delta.get("reasoning_content"):
                        reasoning_parts.append(rc)

                    if tc_list := delta.get("tool_calls"):
                        for tc in tc_list:
                            idx = tc["index"]
                            if idx not in tool_calls_raw:
                                tool_calls_raw[idx] = {"id": tc.get("id", ""), "name": "", "arguments": ""}
                            if fn := tc.get("function"):
                                if name := fn.get("name"):
                                    tool_calls_raw[idx]["name"] = name
                                if args := fn.get("arguments"):
                                    tool_calls_raw[idx]["arguments"] += args

                    if fr := chunk["choices"][0].get("finish_reason"):
                        finish_reason = fr
                    if u := chunk.get("usage"):
                        usage_data = u

        tool_calls = [
            ToolCallRequest(id=v["id"], name=v["name"], arguments=v["arguments"])
            for _, v in sorted(tool_calls_raw.items())
        ] if tool_calls_raw else []

        if tool_calls and finish_reason != "tool_calls":
            finish_reason = "tool_calls"

        yield ModelResponse(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
            ),
            finish_reason=finish_reason,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": request.messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if request.tools:
            payload["tools"] = request.tools
        return payload

    def _parse_response(self, data: dict[str, Any]) -> ModelResponse:
        choice = data["choices"][0]
        message = choice["message"]

        content = message.get("content") or ""
        reasoning_content = message.get("reasoning_content") or ""

        tool_calls: list[ToolCallRequest] = []
        if raw_calls := message.get("tool_calls"):
            for tc in raw_calls:
                tool_calls.append(
                    ToolCallRequest(
                        id=tc.get("id", ""),
                        name=tc["function"]["name"],
                        arguments=tc["function"].get("arguments", ""),
                    )
                )

        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        finish_reason = choice.get("finish_reason", "stop")
        if finish_reason == "tool_calls":
            pass
        elif tool_calls:
            finish_reason = "tool_calls"

        return ModelResponse(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )
