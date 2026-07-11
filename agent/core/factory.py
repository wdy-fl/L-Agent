"""Factory: assemble a fully-wired AgentRunner ready for production use."""

from __future__ import annotations

from agent.actions.model_call import make_llm_call_action, make_llm_stream_action
from agent.actions.tool_call import make_tool_call_action
from agent.config.settings import Settings
from agent.core.runner import AgentRunner
from agent.llm.client import ModelConfig, OpenAICompatibleClient
from agent.middleware.chain import MiddlewareChain
from agent.middleware.model import BudgetGuard, TraceRecord
from agent.middleware.tool import ApprovalGuard, AuditRecord, ResultLimitGuard
from agent.steps.after_agent import (
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
from agent.steps.before_agent import (
    RunStart,
    MessageCommitUser,
    CheckpointCreateUserSnapshot,
    BudgetInitialize,
)
from agent.steps.before_model import (
    IterationCreate,
    ModelRequestCompose,
)
from agent.steps.before_tool import (
    ToolCallsExtract,
    ToolCallsParseArguments,
    ToolCallsValidateSchema,
    ToolCallsResolveTools,
    ToolPlanBuildSerial,
    ApprovalPrepareRequests,
)
from agent.steps.registry import StepRegistry
from agent.tools.builtin import create_builtin_registry, make_web_search_tool
from agent.tools.dispatcher import ToolDispatcher


def build_runner(settings: Settings) -> AgentRunner:
    if not settings.llm.api_key:
        raise RuntimeError(
            "llm.api_key is required. Set it in workspace/config.yaml"
        )

    model_config = ModelConfig(
        model=settings.llm.model,
        api_base=settings.llm.api_base,
        api_key=settings.llm.api_key,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )
    client = OpenAICompatibleClient(model_config)

    tool_registry = create_builtin_registry()
    # web_search 为客户端函数工具，需凭据；仅在 llm.web_search 开启时注册。
    if settings.llm.web_search:
        tool_registry.register(
            make_web_search_tool(settings.llm.api_base, settings.llm.api_key)
        )
    dispatcher = ToolDispatcher(tool_registry)

    reg = StepRegistry()
    # ---- before_agent ----
    reg.register(RunStart())
    reg.register(BudgetInitialize(
        max_iterations=settings.budget.max_iterations,
        max_tokens=settings.budget.max_tokens,
    ))
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
    reg.register(ToolCallsParseArguments())
    reg.register(ToolCallsValidateSchema())
    reg.register(ToolCallsResolveTools())
    reg.register(ToolPlanBuildSerial())
    reg.register(ApprovalPrepareRequests())

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
    chain.add(ApprovalGuard())
    chain.add(AuditRecord())
    chain.add(ResultLimitGuard())

    return AgentRunner(
        registry=reg,
        middleware_chain=chain,
        model_call=make_llm_call_action(client),
        tool_call=make_tool_call_action(dispatcher),
        model_stream=make_llm_stream_action(client),
        tool_schemas=tool_registry.list_schemas(),
    )
