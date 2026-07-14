from __future__ import annotations

import traceback
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Callable, Awaitable

from agent.core.context import RunContext
from agent.core.lifecycle import ActionName, HookPhase
from agent.llm.client import ModelResponse
from agent.middleware.chain import MiddlewareChain
from agent.steps.registry import StepRegistry
from agent.timeline.models import Checkpoint, CheckpointType
from agent.tools.base import ToolCall, ToolResult, ToolResultStatus


class AgentRunner:
    """Drives a single AgentRun through the fixed eight-phase lifecycle.

    run() drives rendering and approval through ctx callbacks instead of
    yielding events, so the CLI loop stays thin.
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
        self._tool_call = tool_call or (lambda _: None)
        self._model_stream = model_stream

    async def run(self, ctx: RunContext) -> None:
        try:
            self._run_phase(HookPhase.before_agent, ctx)
            await self._react_loop(ctx)
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
            if ctx.render is not None:
                ctx.render.show_error(exc)
        finally:
            self._run_phase(HookPhase.after_agent, ctx)

    async def _react_loop(self, ctx: RunContext) -> None:
        render = ctx.render

        while True:
            if ctx.interrupted or ctx.budget.exhausted:
                break

            self._run_phase(HookPhase.before_model, ctx)

            if self._model_stream:
                response = None
                async for item in self._model_stream(ctx):
                    if isinstance(item, str):
                        if render is not None:
                            render.stream_text(item)
                    elif isinstance(item, ModelResponse):
                        response = item
                if response is None:
                    raise RuntimeError("stream ended without ModelResponse")
                ctx.current_model_response = response
                self._record_checkpoint(ActionName.model_call, "completed", ctx)

                if render is not None:
                    render.finish_stream()
                    render.show_reasoning(getattr(response, "reasoning_content", ""))

            self._run_phase(HookPhase.after_model, ctx)

            if ctx.has_tool_calls:
                self._run_phase(HookPhase.before_tool, ctx)

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
                        risk_level = "high" if call.tool_name in ("terminal",) else "medium"
                        if ctx.request_approval is not None:
                            approved = await ctx.request_approval(
                                call.tool_name, call.arguments, risk_level
                            )
                        else:
                            approved = False
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
                    if render is not None:
                        render.show_tool_spinner(tool_call_info.get("name", ""))

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
                    if render is not None:
                        render.finish_tool(
                            tool_result.get("name", ""), tool_result.get("content")
                        )

                self._run_phase(HookPhase.after_tool, ctx)
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

    def _run_phase(self, phase: HookPhase, ctx: RunContext) -> None:
        for step in self._registry.get_steps(phase):
            step.run(ctx)

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