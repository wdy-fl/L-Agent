from __future__ import annotations

import time
import uuid

from agent.core.context import RunContext
from agent.core.lifecycle import HookPhase
from agent.steps.base import Step
from agent.timeline.models import Checkpoint, CheckpointType, RunStatus


class RunFinish(Step):
    """Log run.done and record elapsed time."""

    def __init__(self) -> None:
        super().__init__("run.finish", HookPhase.after_run)

    async def run(self, ctx: RunContext) -> None:
        from agent.logging import get_logger

        ctx.elapsed_ms = (time.time() - ctx.started_at) * 1000
        get_logger().log(
            event="run.done",
            run_id=ctx.run_id,
            status=ctx.status,
            elapsed_ms=round(ctx.elapsed_ms, 1),
            total_iterations=ctx.budget.consumed_iterations,
            total_tokens=ctx.budget.consumed_total_tokens,
        )
        return


class RunMarkTerminalState(Step):
    """Update AgentRun status to completed/failed/interrupted."""

    def __init__(self) -> None:
        super().__init__("run.mark_terminal_state", HookPhase.after_run)

    async def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        status_map = {"completed": RunStatus.completed, "failed": RunStatus.failed, "interrupted": RunStatus.interrupted}
        status = status_map.get(ctx.status, RunStatus.failed)
        store.update_run_status(ctx.run_id, status)
        return


class CheckpointRecordRunTerminalState(Step):
    """Create runtime checkpoint for run terminal state."""

    def __init__(self) -> None:
        super().__init__("checkpoint.record_run_terminal_state", HookPhase.after_run)

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
            type=CheckpointType.runtime,
            message_cursor=cursor,
        )
        store.create_checkpoint(cp)
        return


class RunStatusLogging(Step):
    """Log status-specific events based on ctx.status."""

    def __init__(self) -> None:
        super().__init__("run.status_logging", HookPhase.after_run)

    async def run(self, ctx: RunContext) -> None:
        from agent.logging import get_logger

        logger = get_logger()

        if ctx.status == "completed":
            logger.log(
                event="run.completed",
                run_id=ctx.run_id,
                total_iterations=ctx.budget.consumed_iterations,
                total_tokens=ctx.budget.consumed_total_tokens,
                elapsed_ms=round(ctx.elapsed_ms, 1),
            )
        elif ctx.status == "interrupted":
            logger.log(
                event="run.interrupted",
                run_id=ctx.run_id,
                completed_iterations=ctx.budget.consumed_iterations,
                total_tokens=ctx.budget.consumed_total_tokens,
                elapsed_ms=round(ctx.elapsed_ms, 1),
            )
        elif ctx.status == "exhausted":
            logger.log(
                event="run.exhausted",
                run_id=ctx.run_id,
                total_iterations=ctx.budget.consumed_iterations,
                total_tokens=ctx.budget.consumed_total_tokens,
                max_iterations=ctx.budget.max_iterations,
                max_tokens=ctx.budget.max_tokens,
                elapsed_ms=round(ctx.elapsed_ms, 1),
            )
        elif ctx.status == "error":
            logger.log(
                event="run.error",
                run_id=ctx.run_id,
                error_type=ctx.error_type,
                error_message=ctx.error_message,
                traceback=ctx.error_traceback,
                completed_iterations=ctx.budget.consumed_iterations,
                total_tokens=ctx.budget.consumed_total_tokens,
                elapsed_ms=round(ctx.elapsed_ms, 1),
            )


class BranchUpdateResumeHead(Step):
    """Update branch.resume_head when run completes successfully."""

    def __init__(self) -> None:
        super().__init__("branch.update_resume_head", HookPhase.after_run)

    async def run(self, ctx: RunContext) -> None:
        store = ctx.timeline_store
        if store is None:
            return
        if ctx.status != "completed":
            return
        checkpoints = store.get_checkpoints_by_branch(ctx.branch_id)
        run_completed_cp = None
        for cp in reversed(checkpoints):
            if cp.run_id == ctx.run_id and cp.type == CheckpointType.runtime:
                run_completed_cp = cp
                break
        if run_completed_cp is None:
            return
        branch = store.get_branch(ctx.branch_id)
        if branch is None:
            return
        branch.resume_head = run_completed_cp.checkpoint_id
        store.update_branch(branch)
        return
