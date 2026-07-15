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
        self._renderer = Renderer(self._console)

        auto_approve = set(settings.approval.auto_approve) | AUTO_APPROVE_TOOLS
        always_confirm = set(settings.approval.always_confirm) | ALWAYS_CONFIRM_TOOLS
        self._approval = ApprovalHandler(self._console, auto_approve=auto_approve)
        self._always_confirm = always_confirm
        self._command_dispatcher = CommandDispatcher(self._store, self._console)

    async def _init_agent(self) -> None:
        """Initialize agent components: client, tools, session, context, and runner."""
        model_config = ModelConfig(
            model=self._settings.llm.model,
            base_url=self._settings.llm.base_url,
            api_key=self._settings.llm.api_key,
            temperature=self._settings.llm.temperature,
            max_tokens=self._settings.llm.max_tokens,
        )
        tool_registry = create_builtin_registry()
        if self._settings.llm.web_search:
            tool_registry.register(
                make_web_search_tool(self._settings.llm.base_url, self._settings.llm.api_key)
            )
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

        self._ctx.logger = AgentLogger(
            logs_dir=Path("workspace/logs"),
            session_id=self._ctx.session_id,
        )

        self._ctx.available_tools = tool_registry.list_schemas()
        self._ctx.client = OpenAICompatibleClient(model_config)
        self._ctx.dispatcher = ToolDispatcher(tool_registry)

        # Inject UI callbacks so the runner can drive rendering & approval directly.
        self._ctx.renderer = self._renderer
        self._ctx.request_approval = self._approval.prompt

        self._runner = build_runner()

    async def start(self) -> None:
        """Start the CLI session."""
        await self._init_agent()

        self._console.print()
        self._console.print("[bold cyan]  L-Agent[/bold cyan] [dim]v0.1.0[/dim]")
        self._console.print("[dim]  Type your message to chat, /help for commands, Ctrl+C to exit.[/dim]")
        self._console.print()

        # Esc 中断当前 agent 任务，回到输入提示符（不退出会话）。
        # 由 agent 运行循环检查 self._ctx.interrupted 标志来响应。
        kb = KeyBindings()

        @kb.add(Keys.Escape)
        def _esc(event):
            self._ctx.interrupted = True

        session: PromptSession = PromptSession(key_bindings=kb)

        while True:
            try:
                user_input = await session.prompt_async("❯ ")
            except EOFError:
                break
            except KeyboardInterrupt:
                # Ctrl+C 直接退出整个 CLI 会话。
                self._console.print("[dim]Goodbye.[/dim]")
                break

            if not user_input.strip():
                continue

            if user_input.strip().startswith("/"):
                await self._command_dispatcher.dispatch(user_input.strip(), self._ctx)
                continue

            await self._handle_run(user_input.strip())

    async def _handle_run(self, user_input: str) -> None:
        """Execute an agent run (rendering & approval driven through ctx callbacks)."""
        self._ctx.interrupted = False
        self._ctx.input = user_input

        await self._runner.run(self._ctx)

        if self._ctx.status == "interrupted":
            self._renderer.show_interrupted()
        elif self._ctx.status == "failed":
            self._renderer.show_run_failed()
        elif self._ctx.status in ("completed", "exhausted"):
            self._renderer.show_status(
                self._ctx.budget.consumed_iterations,
                self._ctx.budget.consumed_total_tokens,
                self._ctx.elapsed_ms
            )
            if self._ctx.status == "exhausted":
                self._console.print("[dim]  Budget exhausted — run stopped.[/dim]")
