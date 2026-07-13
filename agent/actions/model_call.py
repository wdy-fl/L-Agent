from __future__ import annotations

from collections.abc import AsyncGenerator

from agent.core.context import RunContext
from agent.llm.client import LLMClient, ModelResponse


def make_llm_stream_action(client: LLMClient):
    """Create a streaming model_call action that yields token strings then ModelResponse."""

    async def llm_stream(ctx: RunContext) -> AsyncGenerator[str | ModelResponse, None]:
        if ctx.current_model_request is None:
            raise RuntimeError("model_request not set before llm.call")
        async for item in client.stream(ctx.current_model_request):
            yield item

    return llm_stream
