from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from agent.llm.types import ModelRequest, ModelResponse, ToolCallRequest, Usage


class LLMClient(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def call(self, request: ModelRequest) -> ModelResponse: ...


class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible client (supports DeepSeek, GPT, Claude-compatible endpoints)."""

    def __init__(self, api_base: str, api_key: str, timeout: float = 120.0) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def call(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._api_base}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        return self._parse_response(resp.json())

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = request.tools
        return payload

    def _parse_response(self, data: dict[str, Any]) -> ModelResponse:
        choice = data["choices"][0]
        message = choice["message"]

        content = message.get("content") or ""

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
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )
