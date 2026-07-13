from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Callable, Awaitable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName, HookPhase
from agent.core.events import (
    AgentEvent,
    ApprovalRequest,
    ModelStart,
    ModelDone,
    RunError,
    Token,
    ToolDone,
    ToolStart,
)
from agent.llm.client import ModelResponse
from agent.middleware.chain import MiddlewareChain
from agent.steps.registry import StepRegistry
from agent.timeline.models import Checkpoint, CheckpointType
from agent.tools.base import ToolCall, ToolResult, ToolResultStatus


class AgentRunner:
    """Drives a single AgentRun through the fixed eight-phase lifecycle.

    run() is an async generator that yields AgentEvent instances.
    """

    def __init__(
        self,
        registry: StepRegistry,
        middleware_chain: MiddlewareChain,
        tool_call: Callable[[RunContext], Any] | Callable[[RunContext], Awaitable[Any]] | None = None,
        model_stream: Callable[[RunContext], AsyncGenerator[str | ModelResponse, None]] | None = None,
    ) -> None:
        self._registry = registry
        self._chain = middleware_chain
        self._tool_call = tool_call or self._noop_tool_call
        self._model_stream = model_stream

    async def run(self, ctx: RunContext) -> AsyncGenerator[AgentEvent, None]:
        try:
            for event in self._run_phase(HookPhase.before_agent, ctx):
                yield event
            async for event in self._react_loop(ctx):
                yield event
            if ctx.interrupted:
                ctx.status = "interrupted"
            else:
                ctx.status = "completed"
        except Exception as exc:
            ctx.status = "failed"
            if ctx.logger:
                ctx.logger.log(
                    event="run.error",
                    run_id=ctx.run_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    traceback=traceback.format_exc(),
                )
            yield RunError(error=exc)
        finally:
            for event in self._run_phase(HookPhase.after_agent, ctx):
                yield event

    async def _react_loop(self, ctx: RunContext) -> AsyncGenerator[AgentEvent, None]:
        while True:
            if ctx.interrupted or ctx.budget.exhausted:
                break

            for event in self._run_phase(HookPhase.before_model, ctx):
                yield event

            yield ModelStart()

            if self._model_stream:
                t_model = time.time()
                if ctx.logger:
                    req = ctx.current_model_request
                    ctx.logger.log(
                        event="model.start",
                        run_id=ctx.run_id,
                        iteration=ctx.budget.consumed_iterations,
                        messages_count=len(req.messages) if req else 0,
                        tools_count=len(req.tools) if req else 0,
                    )

                response = None
                async for item in self._model_stream(ctx):
                    if isinstance(item, str):
                        yield Token(text=item)
                    elif isinstance(item, ModelResponse):
                        response = item
                if response is None:
                    raise RuntimeError("stream ended without ModelResponse")
                ctx.current_model_response = response
                self._record_checkpoint(ActionName.model_call, "completed", ctx)

                if ctx.logger and response is not None:
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
            yield ModelDone(response=ctx.current_model_response or ModelResponse())

            for event in self._run_phase(HookPhase.after_model, ctx):
                yield event

            if ctx.has_tool_calls:
                for event in self._run_phase(HookPhase.before_tool, ctx):
                    yield event

                plan = ctx.current_tool_plan
                if plan and hasattr(plan, "calls") and plan.calls and ctx.always_confirm_tools:
                    approved_calls: list[ToolCall] = []
                    for call in plan.calls:
                        if call.error:
                            approved_calls.append(call)
                            continue
                        if call.tool_name not in ctx.always_confirm_tools:
                            approved_calls.append(call)
                            continue
                        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
                        yield ApprovalRequest(
                            tool_name=call.tool_name,
                            arguments=call.arguments,
                            risk_level="high" if call.tool_name in ("terminal",) else "medium",
                            future=future,
                        )
                        approved = await future
                        if approved:
                            approved_calls.append(call)
                        else:
                            result = ToolResult(
                                call_id=call.call_id,
                                status=ToolResultStatus.denied,
                                content=f"Tool '{call.tool_name}' was denied by user.",
                            )
                            if ctx.current_tool_results is None:
                                ctx.current_tool_results = []
                            ctx.current_tool_results.append(result)
                    plan.calls = approved_calls

                for tool_call_info in self._get_tool_calls(ctx):
                    yield ToolStart(tool_name=tool_call_info.get("name", ""), arguments=tool_call_info.get("arguments", {}))

                should_execute = (plan is None) or (not hasattr(plan, "calls")) or plan.calls
                if should_execute:
                    self._record_checkpoint(ActionName.tool_call, "started", ctx)
                    try:
                        wrapped = self._chain.execute(ActionName.tool_call, ctx, lambda: self._tool_call(ctx))
                        if hasattr(wrapped, "__await__"):
                            ctx.current_tool_results = await wrapped
                        else:
                            ctx.current_tool_results = wrapped
                        self._record_checkpoint(ActionName.tool_call, "completed", ctx)
                    except Exception:
                        self._record_checkpoint(ActionName.tool_call, "failed", ctx)
                        raise

                for tool_result in self._get_tool_results(ctx):
                    yield ToolDone(tool_name=tool_result.get("name", ""), result=tool_result.get("content"))

                for event in self._run_phase(HookPhase.after_tool, ctx):
                    yield event
                ctx.has_tool_calls = False
            else:
                break

    def _get_tool_calls(self, ctx: RunContext) -> list[dict]:
        if ctx.current_tool_plan is None:
            return []
        plan = ctx.current_tool_plan
        if hasattr(plan, "calls"):
            return [{"name": c.tool_name, "arguments": c.arguments} for c in plan.calls]
        return []

    def _get_tool_results(self, ctx: RunContext) -> list[dict]:
        results = ctx.current_tool_results
        if results is None:
            return []
        if isinstance(results, list):
            return [{"name": getattr(r, "call_id", ""), "content": getattr(r, "content", str(r))} for r in results]
        return []

    def _run_phase(self, phase: HookPhase, ctx: RunContext) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for step in self._registry.get_steps(phase):
            events.extend(step.run(ctx))
        return events

    def _record_checkpoint(self, action: ActionName, status: str, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        name = f"{action.value}_{status}"
        cursor = store.get_latest_sequence(ctx.branch_id)
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            type=CheckpointType.runtime,
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)

    @staticmethod
    async def _noop_tool_call(ctx: RunContext) -> Any:
        return None

    async def run_to_completion(self, ctx: RunContext) -> RunContext:
        """Drain the event stream and return the final context."""
        async for _ in self.run(ctx):
            pass
        return ctx
