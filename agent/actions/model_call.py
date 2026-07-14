from __future__ import annotations

import time
from collections.abc import AsyncGenerator

from agent.core.context import RunContext
from agent.llm.client import LLMClient, ModelResponse


def make_llm_stream_action(client: LLMClient):
    """Create a streaming model_call action that yields token strings then ModelResponse."""

    async def llm_stream(ctx: RunContext) -> AsyncGenerator[str | ModelResponse, None]:
        if ctx.current_model_request is None:
            raise RuntimeError("model_request not set before llm.call")

        t_model = time.time()
        req = ctx.current_model_request
        if ctx.logger:
            ctx.logger.log(
                event="model.start",
                run_id=ctx.run_id,
                iteration=ctx.budget.consumed_iterations,
                messages_count=len(req.messages) if req else 0,
                tools_count=len(req.tools) if req else 0,
            )

        response: ModelResponse | None = None
        async for item in client.stream(ctx.current_model_request):
            if isinstance(item, ModelResponse):
                response = item
            yield item

        if response is not None and ctx.logger:
            elapsed_ms = (time.time() - t_model) * 1000
            ctx.logger.log(
                event="model.done",
                run_id=ctx.run_id,
                iteration=ctx.budget.consumed_iterations,
                elapsed_ms=round(elapsed_ms, 1),
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
                finish_reason=response.finish_reason,
                content=response.content,
                reasoning_content=response.reasoning_content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            )

    return llm_stream
