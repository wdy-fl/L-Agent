from __future__ import annotations

import json

import uuid
from typing import Any

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelResponse
from agent.steps.base import Step
from agent.timeline.models import Checkpoint, CheckpointType
from agent.tools.base import ToolCall, ToolResult, ToolResultStatus


class ToolCallsExtract(Step):
    """Extract tool_calls from model response, parse arguments, validate, and
    build a serial execution plan — all in one step."""

    def __init__(self) -> None:
        super().__init__("tool_calls.extract", HookPhase.before_tool)

    async def run(self, ctx: RunContext) -> None:
        resp = ctx.current_model_response
        if resp is None or not isinstance(resp, ModelResponse):
            return

        # 1. Extract tool_calls into ToolCall objects
        calls: list[ToolCall] = []
        for tc in resp.tool_calls:
            calls.append(ToolCall(
                call_id=tc["id"],
                tool_name=tc["function"]["name"],
                arguments={},
            ))

        # 2. Parse JSON arguments
        for i, call in enumerate(calls):
            raw_args = resp.tool_calls[i]["function"]["arguments"]
            if not raw_args or raw_args.strip() == "":
                call.arguments = {}
                continue
            try:
                parsed = json.loads(raw_args)
                if not isinstance(parsed, dict):
                    call.error = f"Arguments must be a JSON object, got {type(parsed).__name__}"
                    continue
                call.arguments = parsed
            except json.JSONDecodeError as exc:
                call.error = f"Failed to parse arguments: {exc}"

        # 3. Build available-tools lookup
        available_tools: dict[str, Any] = {}
        available_names: set[str] = set()
        for tool_schema in ctx.available_tools:
            func_def = tool_schema.get("function", {})
            name = func_def.get("name", "")
            if name:
                available_tools[name] = func_def
                available_names.add(name)

        # 4. Validate schema & resolve tool existence
        for call in calls:
            if call.error:
                continue

            spec = available_tools.get(call.tool_name)
            if spec is not None:
                schema = spec.get("parameters", {})
                required = schema.get("required", [])
                properties = schema.get("properties", {})

                for param_name in required:
                    if param_name not in call.arguments:
                        call.error = f"Missing required parameter: {param_name}"
                        break

                if not call.error:
                    for param_name in call.arguments:
                        if properties and param_name not in properties:
                            call.error = f"Unknown parameter: {param_name}"
                            break

            if call.tool_name not in available_names:
                call.error = f"Tool not available: {call.tool_name}"

        ctx.current_tool_calls = calls
        return


class ToolsApproval(Step):
    """Check always_confirm_tools, request user approval, and deny unapproved calls."""

    def __init__(self) -> None:
        super().__init__("tools.approval", HookPhase.before_tool)

    async def run(self, ctx: RunContext) -> None:
        calls = ctx.current_tool_calls
        if not calls or not ctx.always_confirm_tools:
            return

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


class ToolExecutionStart(Step):
    """Show tool spinner, record checkpoint, and log tool.start events."""

    def __init__(self) -> None:
        super().__init__("tools.execution_start", HookPhase.before_tool)

    async def run(self, ctx: RunContext) -> None:
        calls = ctx.current_tool_calls
        if not calls:
            return

        # Show a single spinner covering all tool calls in this batch —
        # per-tool spinners would overwrite each other and only the last
        # would be visible (see show_tool_spinner).
        renderer = ctx.renderer
        if renderer is not None:
            renderer.show_tool_spinner([call.tool_name for call in calls])

        # Record checkpoint: tool_call started
        store = ctx.timeline_store
        if store is not None:
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

        # Log tool.start events
        from agent.logging import get_logger

        logger = get_logger()
        for tc in calls:
            logger.log(
                event="tool.start",
                run_id=ctx.run_id,
                tool_name=tc.tool_name,
                arguments=tc.arguments,
            )