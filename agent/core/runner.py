from __future__ import annotations

import time
import traceback
import uuid
from agent.core.context import RunContext
from agent.core.lifecycle import ActionName, HookPhase
from agent.llm.client import ModelResponse
from agent.steps.registry import StepRegistry
from agent.timeline.models import Checkpoint, CheckpointType
from agent.tools.base import ToolCall, ToolResult, ToolResultStatus


class AgentRunner:
    """Drives a single AgentRun through the fixed eight-phase lifecycle.

    run() drives rendering and approval through ctx callbacks instead of
    yielding events, so the CLI loop stays thin.
    """

    def __init__(self, registry: StepRegistry) -> None:
        self._registry = registry

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
            self._run_phase(HookPhase.before_model, ctx)

            if ctx.interrupted or ctx.budget.exhausted:
                break

            # --- model call ---
            if ctx.current_model_request is None:
                raise RuntimeError("model_request not set before model call")

            t0 = time.time()
            if ctx.logger is not None:
                req = ctx.current_model_request
                ctx.logger.log(
                    event="model.start",
                    run_id=ctx.run_id,
                    iteration=ctx.budget.consumed_iterations,
                    messages_count=len(req.messages) if req else 0,
                    tools_count=len(req.tools) if req else 0,
                )

            response = None
            async for item in ctx.client.stream(ctx.current_model_request):
                if isinstance(item, str):
                    if render is not None:
                        render.stream_text(item)
                elif isinstance(item, ModelResponse):
                    response = item
            if response is None:
                raise RuntimeError("stream ended without ModelResponse")
            ctx.current_model_response = response
            self._record_checkpoint(ActionName.model_call, "completed", ctx)

            if ctx.logger is not None:
                elapsed_ms = (time.time() - t0) * 1000
                ctx.logger.log(
                    event="model.done",
                    run_id=ctx.run_id,
                    iteration=ctx.budget.consumed_iterations,
                    elapsed_ms=round(elapsed_ms, 1),
                    tokens_in=response.usage.input_tokens if response else 0,
                    tokens_out=response.usage.output_tokens if response else 0,
                    finish_reason=response.finish_reason if response else "",
                    content=response.content if response else "",
                    reasoning_content=response.reasoning_content if response else "",
                    tool_calls=[
                        {"id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
                        for tc in (response.tool_calls if response else [])
                    ],
                )

            if render is not None:
                render.finish_stream()
                render.show_reasoning(getattr(response, "reasoning_content", ""))

            self._run_phase(HookPhase.after_model, ctx)

            if ctx.has_tool_calls:
                self._run_phase(HookPhase.before_tool, ctx)

                await self._execute_tool(ctx)

                self._run_phase(HookPhase.after_tool, ctx)
                ctx.has_tool_calls = False
            else:
                break

    async def _execute_tool(self, ctx: RunContext) -> None:
        """Run the tool-call phase: approval, execution, and rendering."""
        render = ctx.render
        calls = ctx.current_tool_calls

        if calls and ctx.always_confirm_tools:
            approved_calls: list[ToolCall] = []
            for call in calls:
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
            ctx.current_tool_calls = approved_calls
            calls = approved_calls

        for call in ctx.current_tool_calls or []:
            if render is not None:
                render.show_tool_spinner(call.tool_name)

        should_execute = calls is None or bool(calls)
        if should_execute:
            self._record_checkpoint(ActionName.tool_call, "started", ctx)

            # --- AuditRecord start (inlined from middleware) ---
            t0 = time.time()
            call_id_to_name: dict[str, str] = {}
            if ctx.logger is not None and calls:
                for tc in calls:
                    call_id_to_name[tc.call_id] = tc.tool_name
                    ctx.logger.log(
                        event="tool.start",
                        run_id=ctx.run_id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                    )

            try:
                results = ctx.dispatcher.dispatch(ctx.current_tool_calls or [])
                ctx.current_tool_results = results

                # --- AuditRecord end (inlined from middleware) ---
                elapsed_ms = (time.time() - t0) * 1000
                if ctx.logger is not None and isinstance(results, list):
                    for r in results:
                        if isinstance(r, ToolResult):
                            tool_name = call_id_to_name.get(r.call_id, r.call_id)
                            ctx.logger.log(
                                event="tool.done",
                                run_id=ctx.run_id,
                                tool_name=tool_name,
                                elapsed_ms=round(elapsed_ms, 1),
                                status=r.status.value,
                                result=r.content,
                            )

                # --- ResultLimitGuard (inlined from middleware) ---
                if isinstance(results, list):
                    for result in results:
                        if isinstance(result, ToolResult) and len(result.content) > 50_000:
                            result.content = (
                                result.content[:50_000]
                                + f"\n\n[Truncated: result exceeded 50_000 characters]"
                            )

                self._record_checkpoint(ActionName.tool_call, "completed", ctx)
            except Exception:
                self._record_checkpoint(ActionName.tool_call, "failed", ctx)
                raise

        results = ctx.current_tool_results
        if isinstance(results, list):
            for result in results:
                if render is not None:
                    render.finish_tool(
                        getattr(result, "call_id", ""), getattr(result, "content", str(result))
                    )

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