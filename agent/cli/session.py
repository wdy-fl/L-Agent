"""CLI interactive session: main loop + event rendering."""

from __future__ import annotations

import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console

from agent.cli.approval import ApprovalHandler
from agent.cli.commands import CommandDispatcher
from agent.cli.render import Renderer
from agent.config.settings import Settings
from agent.core.context import RunContext
from agent.core.factory import build_runner
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
from agent.timeline.session_factory import create_session_with_default_branch
from agent.tools.builtin import ALWAYS_CONFIRM_TOOLS, AUTO_APPROVE_TOOLS

console = Console()


class CLISession:
    """Manages one interactive CLI session."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self._runner = build_runner(settings)

        db_path = Path(settings.storage.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = SQLiteTimelineStore(db_path)

        self._console = console
        self._render = Renderer(console)

        auto_approve = set(settings.approval.auto_approve) | AUTO_APPROVE_TOOLS
        always_confirm = set(settings.approval.always_confirm) | ALWAYS_CONFIRM_TOOLS
        self._approval = ApprovalHandler(console, auto_approve=auto_approve)
        self._always_confirm = always_confirm
        self._commands = CommandDispatcher(self._store, console)

        self._session_id: str = ""
        self._branch_id: str = ""
        self._interrupted = False

    async def start(self) -> None:
        """Start the CLI session."""
        session = create_session_with_default_branch(self._store)
        self._session_id = session.session_id
        self._branch_id = session.active_branch_id

        self._commands.session_id = self._session_id
        self._commands.branch_id = self._branch_id

        self._console.print()
        self._console.print("[bold cyan]  L-Agent[/bold cyan] [dim]v0.1.0[/dim]")
        self._console.print("[dim]  Type your message to chat, /help for commands, Ctrl+C to exit.[/dim]")
        self._console.print()

        await self._main_loop()

    async def _main_loop(self) -> None:
        """Main input loop."""
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
                await self._commands.dispatch(user_input.strip())
                self._session_id = self._commands.session_id
                self._branch_id = self._commands.branch_id
                continue

            await self._handle_run(user_input.strip())

    async def _handle_run(self, user_input: str) -> None:
        """Execute an agent run and render events."""
        self._interrupted = False
        ctx = RunContext(
            input=user_input,
            session_id=self._session_id,
            branch_id=self._branch_id,
            timeline_store=self._store,
            auto_approve_tools=self._approval._auto_approve,
            always_confirm_tools=self._always_confirm,
        )

        start_time = time.time()

        async for event in self._runner.run(ctx):
            if self._interrupted:
                ctx.interrupted = True

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

        elapsed_ms = (time.time() - start_time) * 1000
        total_tokens = ctx.budget.consumed_total_tokens

        if ctx.interrupted:
            self._render.show_interrupted()
        elif ctx.status == "completed":
            self._render.show_status(ctx.budget.consumed_iterations, total_tokens, elapsed_ms)
