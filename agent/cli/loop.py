"""CLI interactive session: main loop + event rendering."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

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
from agent.timeline.models import Message
from agent.timeline.resume import resume
from agent.timeline.session_factory import create_session_with_default_branch
from agent.tools.builtin import ALWAYS_CONFIRM_TOOLS, AUTO_APPROVE_TOOLS, create_builtin_registry, make_web_search_tool
from agent.tools.dispatcher import ToolDispatcher


def _message_to_dict(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = message.tool_calls
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    return data

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
        self._commands = CommandDispatcher(self._store, self._console)

        self._session_id: str = ""
        self._branch_id: str = ""
        self._interrupted = False

    async def start(self) -> None:
        """Start the CLI session."""
        model_config = ModelConfig(
            model=self._settings.llm.model,
            api_base=self._settings.llm.api_base,
            api_key=self._settings.llm.api_key,
            temperature=self._settings.llm.temperature,
            max_tokens=self._settings.llm.max_tokens,
        )
        client = OpenAICompatibleClient(model_config)

        tool_registry = create_builtin_registry()
        if self._settings.llm.web_search:
            tool_registry.register(
                make_web_search_tool(self._settings.llm.api_base, self._settings.llm.api_key)
            )
        dispatcher = ToolDispatcher(tool_registry)

        self._runner = build_runner(
            self._settings, client, dispatcher, tool_registry.list_schemas()
        )

        session = create_session_with_default_branch(self._store)
        self._session_id = session.session_id
        self._branch_id = session.active_branch_id

        self._commands.session_id = self._session_id
        self._commands.branch_id = self._branch_id

        self._logger = AgentLogger(
            logs_dir=Path("workspace/logs"),
            session_id=self._session_id,
        )

        self._ctx = RunContext(
            session_id=self._session_id,
            branch_id=self._branch_id,
            timeline_store=self._store,
            auto_approve_tools=self._approval._auto_approve,
            always_confirm_tools=self._always_confirm,
            logger=self._logger,
        )

        history = resume(self._store, self._session_id)
        if history.messages:
            self._ctx.messages = [_message_to_dict(message) for message in history.messages]
        else:
            system_prompt = Path("workspace/AGENT.md").read_text(encoding="utf-8")
            self._ctx.messages.append({"role": "system", "content": system_prompt})
            seq = self._store.get_latest_sequence(self._branch_id) + 1
            self._store.append_message(
                Message(
                    message_id=str(uuid.uuid4()),
                    session_id=self._session_id,
                    branch_id=self._branch_id,
                    run_id="",
                    sequence=seq,
                    role="system",
                    content=system_prompt,
                )
            )

        self._ctx.available_tools = self._runner.tool_schemas

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
