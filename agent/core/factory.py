"""Factory: assemble a fully-wired AgentRunner ready for production use."""

from __future__ import annotations

from agent.core.runner import AgentRunner
from agent.steps.after_run import (
    RunFinish,
    RunMarkTerminalState,
    CheckpointRecordRunTerminalState,
    BranchUpdateResumeHead,
)
from agent.steps.after_model import (
    MessageCommitAssistant,
    UsageUpdate,
    ResultDetectRouting,
)
from agent.steps.after_tool import (
    MessageCommitToolResults,
    ResultLimitGuard,
    ToolDoneLogging,
    ToolResultsCapture,
    ToolResultsRender,
)
from agent.steps.before_run import (
    RunStart,
    MessageCommitUser,
    CheckpointCreateUserSnapshot,
)
from agent.steps.before_model import (
    BudgetGuard,
    IterationCreate,
    ModelRequestCompose,
)
from agent.steps.before_tool import (
    ToolCallsExtract,
    ToolsApproval,
    ToolExecutionStart,
)
from agent.steps.registry import StepConfig, StepRegistry


def build_runner() -> AgentRunner:
    reg = StepRegistry()
    # ---- before_agent ----
    reg.register(RunStart())
    reg.register(MessageCommitUser())
    reg.register(CheckpointCreateUserSnapshot())

    # ---- before_model ----
    reg.register(BudgetGuard(), StepConfig(priority=10))
    reg.register(IterationCreate())
    reg.register(ModelRequestCompose())

    # ---- after_model ----
    reg.register(MessageCommitAssistant())
    reg.register(UsageUpdate())
    reg.register(ResultDetectRouting())

    # ---- before_tool ----
    reg.register(ToolCallsExtract())
    reg.register(ToolsApproval())
    reg.register(ToolExecutionStart())

    # ---- after_tool ----
    reg.register(ToolResultsCapture())
    reg.register(ToolDoneLogging())
    reg.register(ResultLimitGuard())
    reg.register(MessageCommitToolResults())
    reg.register(ToolResultsRender())

    # ---- after_agent ----
    reg.register(RunMarkTerminalState())
    reg.register(CheckpointRecordRunTerminalState())
    reg.register(BranchUpdateResumeHead())
    reg.register(RunFinish())

    return AgentRunner(registry=reg)
