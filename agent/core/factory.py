"""Factory: assemble a fully-wired AgentRunner ready for production use."""

from __future__ import annotations

from agent.actions.model_call import make_llm_stream_action
from agent.actions.tool_call import make_tool_call_action
from agent.core.context import RunContext
from agent.core.runner import AgentRunner
from agent.middleware.chain import MiddlewareChain
from agent.middleware.model import BudgetGuard, TraceRecord
from agent.middleware.tool import AuditRecord, ResultLimitGuard
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
from agent.steps.after_tool import ToolResultsCapture, MessageCommitToolResults
from agent.steps.before_run import (
    RunStart,
    MessageCommitUser,
    CheckpointCreateUserSnapshot,
)
from agent.steps.before_model import (
    IterationCreate,
    ModelRequestCompose,
)
from agent.steps.before_tool import ToolCallsExtract
from agent.steps.registry import StepRegistry


def build_runner(ctx: RunContext) -> AgentRunner:
    reg = StepRegistry()
    # ---- before_agent ----
    reg.register(RunStart())
    reg.register(MessageCommitUser())
    reg.register(CheckpointCreateUserSnapshot())

    # ---- before_model ----
    reg.register(IterationCreate())
    reg.register(ModelRequestCompose())

    # ---- after_model ----
    reg.register(MessageCommitAssistant())
    reg.register(UsageUpdate())
    reg.register(ResultDetectRouting())

    # ---- before_tool ----
    reg.register(ToolCallsExtract())

    # ---- after_tool ----
    reg.register(ToolResultsCapture())
    reg.register(MessageCommitToolResults())

    # ---- after_agent ----
    reg.register(RunMarkTerminalState())
    reg.register(CheckpointRecordRunTerminalState())
    reg.register(BranchUpdateResumeHead())
    reg.register(RunFinish())

    chain = MiddlewareChain()
    chain.add(BudgetGuard())
    chain.add(TraceRecord())

    chain.add(AuditRecord())
    chain.add(ResultLimitGuard())

    return AgentRunner(
        registry=reg,
        middleware_chain=chain,
        tool_call=make_tool_call_action(ctx.dispatcher),
        model_stream=make_llm_stream_action(ctx.client),
    )
