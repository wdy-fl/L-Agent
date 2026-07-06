from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class CheckpointType(str, Enum):
    user_snapshot = "user_snapshot"
    runtime = "runtime"


@dataclass
class Session:
    session_id: str
    title: str = ""
    active_branch_id: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Branch:
    branch_id: str
    session_id: str
    parent_branch_id: str = ""
    fork_checkpoint_id: str = ""
    base_message_cursor: int = 0
    resume_head: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass
class AgentRun:
    run_id: str
    session_id: str
    branch_id: str
    status: RunStatus = RunStatus.running
    created_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None


@dataclass
class ReActIteration:
    iteration_id: str
    run_id: str
    index: int = 0


@dataclass
class Message:
    message_id: str
    session_id: str
    branch_id: str
    run_id: str
    sequence: int
    role: str  # system / user / assistant / tool
    content: str = ""
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)


@dataclass
class Checkpoint:
    checkpoint_id: str
    session_id: str
    branch_id: str
    run_id: str
    type: CheckpointType
    message_cursor: int = 0
    created_at: datetime = field(default_factory=_now)
