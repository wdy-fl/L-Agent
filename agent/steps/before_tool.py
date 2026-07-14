from __future__ import annotations

import json
from typing import Any

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelResponse
from agent.steps.base import Step
from agent.tools.base import ToolCall, ToolPlan


class ToolCallsExtract(Step):
    """Extract tool_calls from model response, parse arguments, validate, and
    build a serial execution plan — all in one step."""

    def __init__(self) -> None:
        super().__init__("tool_calls.extract", HookPhase.before_tool)

    def run(self, ctx: RunContext) -> None:
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

        plan = ToolPlan(calls=calls)

        # 2. Parse JSON arguments
        for i, call in enumerate(plan.calls):
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
        for call in plan.calls:
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

        # 5. Set serial execution mode
        plan.execution_mode = "serial"

        ctx.current_tool_plan = plan
        return
