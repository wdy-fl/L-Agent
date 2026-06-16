from __future__ import annotations

from typing import Any
import uuid
from pathlib import Path

from agent.core.context import BudgetState, RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelConfig
from agent.steps.base import Step
from agent.timeline.models import AgentRun, Checkpoint, CheckpointKind, Message, RunStatus
from agent.tools.registry import ToolRegistry
from agent.timeline.resume import resume

def _message_to_dict(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = message.tool_calls
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    return data


class RunCreate(Step):
    """Write AgentRun record to TimelineStore (status=running)."""

    def __init__(self) -> None:
        super().__init__("run.create", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        ctx.run_id = str(uuid.uuid4())
        run = AgentRun(run_id=ctx.run_id, session_id=ctx.session_id, branch_id=ctx.branch_id, status=RunStatus.running)
        store.create_run(run)
        ctx.status = "running"


class ContextInitialize(Step):
    """Create RunContext basic fields, initialize empty iterations list."""

    def __init__(self) -> None:
        super().__init__("context.initialize", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        history = resume(ctx.timeline_store, ctx.session_id)
        if history:
            ctx.messages = [_message_to_dict(message) for message in history.messages]
            return
        
        system_prompt = Path("workspace/AGENT.md").read_text(encoding="utf-8")
        ctx.messages.append({"role": "system", "content": system_prompt})
        seq = ctx.timeline_store.get_latest_sequence(ctx.branch_id) + 1
        ctx.timeline_store.append_message(
            Message(
                message_id=str(uuid.uuid4()),
                session_id=ctx.session_id,
                branch_id=ctx.branch_id,
                run_id=ctx.run_id,
                sequence=seq,
                role="system",
                content=system_prompt,
            )
        )


class ToolsSnapshotAvailableTools(Step):
    """Snapshot available tools from ToolRegistry into ctx.base_model_context."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        super().__init__("tools.snapshot_available_tools", HookPhase.before_agent)
        self._registry = registry

    def run(self, ctx: RunContext) -> None:
        if self._registry is None:
            ctx.available_tools = []
        else:
            ctx.available_tools = self._registry.list_schemas()


class BudgetInitialize(Step):
    """Initialize budget state (max iterations, token limits)."""

    def __init__(
        self,
        max_iterations: int = 25,
        max_tokens: int = 200_000,
    ) -> None:
        super().__init__("budget.initialize", HookPhase.before_agent)
        self._max_iterations = max_iterations
        self._max_tokens = max_tokens

    def run(self, ctx: RunContext) -> None:
        ctx.budget = BudgetState(
            max_iterations=self._max_iterations,
            max_tokens=self._max_tokens,
        )


class MessageCommitUser(Step):
    """Persist user input as role=user message to branch timeline."""

    def __init__(self) -> None:
        super().__init__("message.commit_user", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        seq = store.get_latest_sequence(ctx.branch_id) + 1
        msg = Message(
            message_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            sequence=seq,
            role="user",
            content=ctx.input,
        )
        store.append_message(msg)


class CheckpointCreateUserSnapshot(Step):
    """Create user_snapshot checkpoint after committing user message."""

    def __init__(self) -> None:
        super().__init__("checkpoint.create_user_snapshot", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        cursor = store.get_latest_sequence(ctx.branch_id)
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            kind=CheckpointKind.user_snapshot,
            name="user_message_committed",
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)
