from __future__ import annotations

import time
import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.llm.client import ModelConfig
from agent.steps.base import Step
from agent.timeline.models import AgentRun, Checkpoint, CheckpointType, Message, RunStatus


class RunStart(Step):
    """Write AgentRun record to TimelineStore (status=running), log run.start."""

    def __init__(self) -> None:
        super().__init__("run.create", HookPhase.before_run)

    async def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
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
        return



class MessageCommitUser(Step):
    """Persist user input as role=user message to branch timeline."""

    def __init__(self) -> None:
        super().__init__("message.commit_user", HookPhase.before_run)

    async def run(self, ctx: RunContext) -> None:
        ctx.messages.append({"role": "user", "content": ctx.input})
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

        return


class CheckpointCreateUserSnapshot(Step):
    """Create user_snapshot checkpoint after committing user message."""

    def __init__(self) -> None:
        super().__init__("checkpoint.create_user_snapshot", HookPhase.before_run)

    async def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
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

        return
