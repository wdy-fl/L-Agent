from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from agent.llm.types import ModelRequest, ModelResponse, ToolCallRequest, Usage


class LLMClient(ABC):
    """Abstract interface for LLM calls."""

    @abstractmethod
    def call(self, request: ModelRequest) -> ModelResponse: ...

    async def stream(self, request: ModelRequest) -> AsyncGenerator[str | ModelResponse, None]:
        """Stream tokens, yielding str for deltas and ModelResponse as the final item."""
        yield self.call(request)


class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible client (supports DeepSeek, GPT, Claude-compatible endpoints)."""

    def __init__(self, api_base: str, api_key: str, timeout: float = 120.0) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def call(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request)
        headers = self._headers()

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._api_base}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        return self._parse_response(resp.json())

    async def stream(self, request: ModelRequest) -> AsyncGenerator[str | ModelResponse, None]:
        payload = self._build_payload(request)
        payload["stream"] = True

        content_parts: list[str] = []
        tool_calls_raw: dict[int, dict] = {}
        usage_data: dict = {}
        finish_reason = "stop"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._api_base}/v1/chat/completions",
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
