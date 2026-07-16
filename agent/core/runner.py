from __future__ import annotations

import asyncio
import traceback
import uuid
from agent.core.context import RunContext
from agent.core.lifecycle import ActionName, HookPhase
from agent.llm.client import ModelResponse, StreamDelta
from agent.steps.registry import StepRegistry
from agent.timeline.models import Checkpoint, CheckpointType, Message


class AgentRunner:
    """驱动一次 AgentRun 走完固定的八阶段生命周期"""

    def __init__(self, registry: StepRegistry) -> None:
        self._registry = registry

    async def run(self, ctx: RunContext) -> None:
        try:
            await self._run_phase(HookPhase.before_run, ctx)
            await self._react_loop(ctx)
            if ctx.interrupted:
                ctx.status = "interrupted"
            elif ctx.budget.exhausted:
                ctx.status = "exhausted"
            else:
                ctx.status = "completed"
        except Exception as exc:
            ctx.status = "error"
            ctx.error_type = type(exc).__name__
            ctx.error_message = str(exc)
            ctx.error_traceback = traceback.format_exc()
            # 如果运行在 after_model 提交了 tool_call 批次之后、after_tool
            # 提交其结果之前中止，就会产生孤儿 tool_call。为这些孤儿
            # tool_call 合成错误结果，避免下一轮的模型请求因
            # "tool_calls 缺少 tool 消息" 而被拒绝。
            self._repair_orphan_tool_calls(ctx)
        finally:
            await self._run_phase(HookPhase.after_run, ctx)

    async def _react_loop(self, ctx: RunContext) -> None:
        renderer = ctx.renderer

        while True:

            await self._run_phase(HookPhase.before_model, ctx)

            if ctx.interrupted or ctx.budget.exhausted:
                break

            response = None
            async for item in ctx.client.stream(ctx.current_model_request):
                if isinstance(item, StreamDelta):
                    if item.kind == "reasoning":
                        renderer.stream_reasoning(item.text)
                    elif item.kind == "content":
                        renderer.stream_text(item.text)
                elif isinstance(item, ModelResponse):
                    response = item
                    renderer.finish_stream()
            if response is None:
                raise RuntimeError("stream ended without ModelResponse")
            ctx.current_model_response = response
            self._record_checkpoint(ActionName.model_call, "completed", ctx)

            await self._run_phase(HookPhase.after_model, ctx)

            if ctx.has_tool_calls:
                await self._run_phase(HookPhase.before_tool, ctx)

                await self._execute_tool(ctx)

                await self._run_phase(HookPhase.after_tool, ctx)
                ctx.has_tool_calls = False
            else:
                break

    async def _execute_tool(self, ctx: RunContext) -> None:
        """执行工具调用阶段：仅做分发。

        审批、spinner、tool.start 以及 checkpoint（started）由
        before_tool 阶段的步骤处理（ToolsApproval、ToolExecutionStart）。

        审计日志、结果截断、completed checkpoint 以及渲染由
        after_tool 阶段的步骤处理（ToolDoneLogging、ResultLimitGuard、
        ToolResultsRender）。
        """
        calls = ctx.current_tool_calls

        should_execute = calls is None or bool(calls)
        if not should_execute:
            return

        try:
            # 在工作线程中执行，避免阻塞型工具处理器（如 terminal 的
            # subprocess.run）卡住 asyncio 事件循环——这样工具执行期间
            # spinner 仍能动画、UI 仍能响应。
            results = await asyncio.to_thread(
                ctx.dispatcher.dispatch, ctx.current_tool_calls or []
            )
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

    def _repair_orphan_tool_calls(self, ctx: RunContext) -> None:
        """为任何缺少应答的 tool_call 追加合成的错误结果。

        扫描消息历史，找出没有对应 ``role=tool`` 消息的 assistant
        tool_calls，并为每一条提交一个 ``[ERROR]`` 工具结果（同时写入
        ``ctx.messages`` 和 timeline store）。这样在运行于提交 assistant
        tool_call 消息（after_model）之后、提交其结果（after_tool）之前
        中止时，历史仍能保持自洽——否则下一轮会把孤儿 tool_call 发给
        模型 API 并立即失败。
        """
        messages = ctx.messages
        if not messages:
            return

        answered = {
            m.get("tool_call_id")
            for m in messages
            if isinstance(m, dict) and m.get("role") == "tool"
        }

        orphans: list[tuple[str, str]] = []
        for m in messages:
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            for tc in m.get("tool_calls") or []:
                cid = tc.get("id") if isinstance(tc, dict) else None
                if cid and cid not in answered:
                    name = tc.get("function", {}).get("name", "") if isinstance(tc, dict) else ""
                    orphans.append((cid, name))

        if not orphans:
            return

        store = ctx.timeline_store
        for cid, name in orphans:
            content = f"[ERROR] run aborted before tool '{name}' produced a result"
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": content,
            })
            if store is None:
                continue
            seq = store.get_latest_sequence(ctx.branch_id) + 1
            store.append_message(Message(
                message_id=str(uuid.uuid4()),
                session_id=ctx.session_id,
                branch_id=ctx.branch_id,
                run_id=ctx.run_id,
                sequence=seq,
                role="tool",
                content=content,
                tool_call_id=cid,
            ))