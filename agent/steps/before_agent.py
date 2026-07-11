from __future__ import annotations

import time
from typing import Any
import uuid

from agent.core.context import BudgetState, RunContext
from agent.core.events import RunStart
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelConfig
from agent.steps.base import Step
from agent.timeline.models import AgentRun, Checkpoint, CheckpointType, Message, RunStatus


class RunStart(Step):
    """Write AgentRun record to TimelineStore (status=running), log run.start, emit RunStart event."""

    def __init__(self) -> None:
        super().__init__("run.create", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> list[Any]:
        store = ctx.timeline_store
        if store is None:
            return []
        ctx.started_at = time.time()
        ctx.run_id = str(uuid.uuid4())
        run = AgentRun(run_id=ctx.run_id, session_id=ctx.session_id, branch_id=ctx.branch_id, status=RunStatus.running)
        store.create_run(run)
        ctx.status = "running"
        if ctx.logger:
            ctx.logger.log(
                event="run.start",
                session_id=ctx.session_id,
                branch_id=ctx.branch_id,
                run_id=ctx.run_id,
                input=ctx.input,
            )
        return [RunStart()]


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

    def run(self, ctx: RunContext) -> list[Any]:
        ctx.budget = BudgetState(
            max_iterations=self._max_iterations,
            max_tokens=self._max_tokens,
        )

        return []


class MessageCommitUser(Step):
    """Persist user input as role=user message to branch timeline."""

    def __init__(self) -> None:
        super().__init__("message.commit_user", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> list[Any]:
        ctx.messages.append({"role": "user", "content": ctx.input})
        store = ctx.timeline_store
        if store is None:
            return []
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

        return []


class CheckpointCreateUserSnapshot(Step):
    """Create user_snapshot checkpoint after committing user message."""

    def __init__(self) -> None:
        super().__init__("checkpoint.create_user_snapshot", HookPhase.before_agent)

    def run(self, ctx: RunContext) -> list[Any]:
        store = ctx.timeline_store
        if store is None:
            return []
        cursor = store.get_latest_sequence(ctx.branch_id)
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            type=CheckpointType.user_snapshot,
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)

        return []
