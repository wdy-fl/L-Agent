"""CLI interactive session: main loop + event rendering."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console

from agent.cli.approval import ApprovalHandler
from agent.cli.commands import CommandDispatcher
from agent.cli.render import Renderer
from agent.config.settings import Settings
from agent.core.context import BudgetState, RunContext
from agent.core.factory import build_runner
from agent.llm.client import ModelConfig, OpenAICompatibleClient
from agent.logging.logger import AgentLogger
from agent.core.events import (
    ApprovalRequest,
    ModelDone,
    ModelStart,
    RunDone,
    RunError,
    Token,
    ToolDone,
    ToolStart,
)
from agent.middleware.chain import MiddlewareChain  # noqa: F401
from agent.steps.registry import StepRegistry  # noqa: F401
from agent.storage.sqlite import SQLiteTimelineStore
from agent.tools.builtin import ALWAYS_CONFIRM_TOOLS, AUTO_APPROVE_TOOLS, create_builtin_registry, make_web_search_tool
from agent.tools.dispatcher import ToolDispatcher

class CLILoop:
    """Manages one interactive CLI session."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self._settings = settings

        db_path = Path(settings.storage.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = SQLiteTimelineStore(db_path)

        self._console = Console()
        self._render = Renderer(self._console)

        auto_approve = set(settings.approval.auto_approve) | AUTO_APPROVE_TOOLS
        always_confirm = set(settings.approval.always_confirm) | ALWAYS_CONFIRM_TOOLS
        self._approval = ApprovalHandler(self._console, auto_approve=auto_approve)
        self._always_confirm = always_confirm
        self._command_dispatcher = CommandDispatcher(self._store, self._console)

        self._interrupted = False

    async def _init_agent(self) -> None:
        """Initialize agent components: client, tools, session, context, and runner."""
        model_config = ModelConfig(
            model=self._settings.llm.model,
            base_url=self._settings.llm.base_url,
            api_key=self._settings.llm.api_key,
            temperature=self._settings.llm.temperature,
            max_tokens=self._settings.llm.max_tokens,
        )
        client = OpenAICompatibleClient(model_config)

        tool_registry = create_builtin_registry()
        if self._settings.llm.web_search:
            tool_registry.register(
                make_web_search_tool(self._settings.llm.base_url, self._settings.llm.api_key)
            )
        tool_dispatcher = ToolDispatcher(tool_registry)

        # Create a bare ctx shell, then let /new populate session_id, branch_id, messages.
        self._ctx = RunContext(
            timeline_store=self._store,
            auto_approve_tools=self._approval._auto_approve,
            always_confirm_tools=self._always_confirm,
        )
        self._ctx.budget = BudgetState(
            max_iterations=self._settings.budget.max_iterations,
            max_tokens=self._settings.budget.max_tokens,
        )
        await self._command_dispatcher.dispatch("/new", self._ctx)

        self._logger = AgentLogger(
            logs_dir=Path("workspace/logs"),
            session_id=self._ctx.session_id,
        )
        self._ctx.logger = self._logger

        self._ctx.available_tools = tool_registry.list_schemas()
        self._ctx.client = client
        self._ctx.dispatcher = tool_dispatcher
        self._runner = build_runner(self._ctx)

    async def start(self) -> None:
        """Start the CLI session."""
        await self._init_agent()

        self._console.print()
        self._console.print("[bold cyan]  L-Agent[/bold cyan] [dim]v0.1.0[/dim]")
        self._console.print("[dim]  Type your message to chat, /help for commands, Ctrl+C to exit.[/dim]")
        self._console.print()

        kb = KeyBindings()

        @kb.add(Keys.Escape)
        def _esc(event):
            self._interrupted = True

        session: PromptSession = PromptSession(key_bindings=kb)

        while True:
            try:
                user_input = await session.prompt_async("❯ ")
            except EOFError:
                break
            except KeyboardInterrupt:
                self._console.print("[dim]Goodbye.[/dim]")
                break

            if not user_input.strip():
                continue

            if user_input.strip().startswith("/"):
                await self._command_dispatcher.dispatch(user_input.strip(), self._ctx)
                continue

            await self._handle_run(user_input.strip())

    async def _handle_run(self, user_input: str) -> None:
        """Execute an agent run and render events."""
        self._interrupted = False

        self._ctx.input = user_input

        async for event in self._runner.run(self._ctx):
            if self._interrupted:
                self._ctx.interrupted = True

            match event:
                case Token(text=t):
                    self._render.stream_text(t)
                case ModelStart():
                    pass
                case ModelDone(response=resp):
                    self._render.finish_stream()
                    self._render.show_reasoning(getattr(resp, "reasoning_content", ""))
                case ToolStart(tool_name=name):
                    self._render.show_tool_spinner(name)
                case ToolDone(tool_name=name, result=r):
                    self._render.finish_tool(name, r)
                case ApprovalRequest() as req:
                    approved = await self._approval.prompt(req)
                    req.future.set_result(approved)
                case RunError(error=e):
                    self._render.show_error(e)
                case RunDone():
                    pass

        total_tokens = self._ctx.budget.consumed_total_tokens

        if self._ctx.interrupted:
            self._render.show_interrupted()
        elif self._ctx.status == "completed":
            self._render.show_status(self._ctx.budget.consumed_iterations, total_tokens, self._ctx.elapsed_ms)
