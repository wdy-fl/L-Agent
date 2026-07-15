from __future__ import annotations

import traceback
import uuid
from agent.core.context import RunContext
from agent.core.lifecycle import ActionName, HookPhase
from agent.llm.client import ModelResponse
from agent.steps.registry import StepRegistry
from agent.timeline.models import Checkpoint, CheckpointType


class AgentRunner:
    """Drives a single AgentRun through the fixed eight-phase lifecycle.

    run() drives rendering and approval through ctx callbacks instead of
    yielding events, so the CLI loop stays thin.
    """

    def __init__(self, registry: StepRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RunContext) -> None:
        try:
            await self._run_phase(HookPhase.before_agent, ctx)
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
            await self._run_phase(HookPhase.after_agent, ctx)

    async def _react_loop(self, ctx: RunContext) -> None:
        render = ctx.render

        while True:
            await self._run_phase(HookPhase.before_model, ctx)

            if ctx.interrupted or ctx.budget.exhausted:
                break

            # --- model call ---
            if ctx.current_model_request is None:
                raise RuntimeError("model_request not set before model call")

            response = None
            async for item in ctx.client.stream(
                ctx.current_model_request,
                logger=ctx.logger,
                run_id=ctx.run_id,
                iteration=ctx.budget.consumed_iterations,
            ):
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

            await self._run_phase(HookPhase.after_model, ctx)

            if ctx.has_tool_calls:
                await self._run_phase(HookPhase.before_tool, ctx)

                await self._execute_tool(ctx)

                await self._run_phase(HookPhase.after_tool, ctx)
                ctx.has_tool_calls = False
            else:
                break

    async def _execute_tool(self, ctx: RunContext) -> None:
        """Run the tool-call phase: dispatch only.

        Approval, spinner, tool.start, and checkpoint (started) are handled by
        before_tool steps (ToolsApproval, ToolExecutionStart).

        Audit logging, result truncation, completed checkpoint, and rendering
        are handled by after_tool steps (ToolDoneLogging, ResultLimitGuard,
        ToolResultsRender).
        """
        calls = ctx.current_tool_calls

        should_execute = calls is None or bool(calls)
        if not should_execute:
            return

        try:
            results = ctx.dispatcher.dispatch(ctx.current_tool_calls or [])
            ctx.current_tool_results = results
            self._record_checkpoint(ActionName.tool_call, "completed", ctx)
        except Exception:
            self._record_checkpoint(ActionName.tool_call, "failed", ctx)
            raise

    async def _run_phase(self, phase: HookPhase, ctx: RunContext) -> None:
        for step in self._registry.get_steps(phase):
            await step.run(ctx)

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