from __future__ import annotations

import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.steps.base import Step
from agent.timeline.models import Checkpoint, CheckpointKind, RunStatus


class RunMarkTerminalState(Step):
    """Update AgentRun status to completed/failed/interrupted."""

    def __init__(self) -> None:
        super().__init__("run.mark_terminal_state", HookPhase.after_agent)

    def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        status_map = {"completed": RunStatus.completed, "failed": RunStatus.failed, "interrupted": RunStatus.interrupted}
        status = status_map.get(ctx.status, RunStatus.failed)
        store.update_run_status(ctx.run_id, status)


class CheckpointRecordRunTerminalState(Step):
    """Create runtime checkpoint for run terminal state."""

    def __init__(self) -> None:
        super().__init__("checkpoint.record_run_terminal_state", HookPhase.after_agent)

    def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        cursor = store.get_latest_sequence(ctx.branch_id)
        name = f"run_{ctx.status}"
        cp = Checkpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            branch_id=ctx.branch_id,
            run_id=ctx.run_id,
            kind=CheckpointKind.runtime,
            name=name,
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)
