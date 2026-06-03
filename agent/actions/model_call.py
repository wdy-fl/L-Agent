from __future__ import annotations

from agent.core.context import RunContext
from agent.llm.client import LLMClient
from agent.llm.types import ModelResponse


def make_llm_call_action(client: LLMClient):
    """Create a model_call action that uses the given LLMClient."""

    def llm_call(ctx: RunContext) -> ModelResponse:
        if ctx.current_model_request is None:
            raise RuntimeError("model_request not set before llm.call")
        return client.call(ctx.current_model_request)

    return llm_call
