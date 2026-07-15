"""CLI render layer: Rich-based output rendering."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text


class Renderer:
    """Renders agent events to terminal using Rich."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._stream_buffer: str = ""
        self._live: Live | None = None
        self._reasoning_buffer: str = ""
        self._reasoning_live: Live | None = None
        self._reasoning_streamed: bool = False

    def stream_text(self, text: str) -> None:
        # First content chunk → finalise the reasoning phase so the thinking
        # panel is printed before the answer starts streaming.
        if self._reasoning_live is not None or self._reasoning_buffer:
            self._finalize_reasoning()
        self._stream_buffer += text
        if self._live is None:
            self._live = Live(console=self._console, refresh_per_second=10)
            self._live.start()
        self._live.update(Markdown(self._stream_buffer))

    def stream_reasoning(self, text: str) -> None:
        """Stream reasoning content in real-time with dim italic styling.

        Reasoning models (GLM-5.2, DeepSeek-R1) emit their chain-of-thought
        *before* the final answer.  This method renders that thinking process
        as it arrives so the user can watch the model reason.
        """
        self._reasoning_buffer += text
        self._reasoning_streamed = True
        if self._reasoning_live is None:
            self._reasoning_live = Live(console=self._console, refresh_per_second=10, transient=True)
            self._reasoning_live.start()
        self._reasoning_live.update(Text(self._reasoning_buffer, style="dim italic"))

    def _finalize_reasoning(self) -> None:
        """Stop the reasoning Live region and print the final collapsed panel."""
        if self._reasoning_live is not None:
            self._reasoning_live.stop()
            self._reasoning_live = None
        if self._reasoning_buffer.strip():
            self._console.print(Panel(
                Text(self._reasoning_buffer, style="dim italic"),
                title="💭 Thinking",
                border_style="dim",
                expand=False,
            ))
        self._reasoning_buffer = ""

    def finish_stream(self) -> None:
        if self._live is not None:
            self._live.update(Markdown(self._stream_buffer))
            self._live.stop()
            self._live = None
        self._stream_buffer = ""


    def show_tool_spinner(self, tool_name: str) -> None:
        self._console.print(
            Spinner("dots", text=Text(f" Running {tool_name}...", style="dim")),
            end="",
        )

    def finish_tool(self, tool_name: str, result) -> None:
        # Clear the spinner line: \r moves to column 0, spaces overwrite the
        # spinner text, \r positions the cursor for the Panel that follows.
        width = self._console.width or 80
        self._console.print(f"\r{' ' * width}\r", end="")
        content = str(result) if result else ""
        if len(content) > 500:
            content = content[:500] + "..."
        self._console.print(Panel(
            content,
            title=f"[bold green]✓[/bold green] {tool_name}",
            border_style="green",
            expand=False,
        ))

    def show_error(self, ctx) -> None:
        """Display error info from the run context."""
        error_msg = f"[bold]{ctx.error_type}[/bold]: {ctx.error_message}"
        if ctx.error_traceback:
            error_msg += f"\n\n[dim]{ctx.error_traceback}[/dim]"
        self._console.print(Panel(
            error_msg,
            title="[bold red]Error[/bold red]",
            border_style="red",
        ))

    def show_status(self, iterations: int, tokens: int, elapsed_ms: float) -> None:
        elapsed_s = elapsed_ms / 1000
        self._console.print(
            f"[dim]── {iterations} iteration(s) · {tokens} tokens · {elapsed_s:.1f}s[/dim]"
        )

    def show_banner(self) -> None:
        """Print the welcome banner at session start."""
        self._console.print()
        self._console.print("[bold cyan]  L-Agent[/bold cyan] [dim]v0.1.0[/dim]")
        self._console.print("[dim]  Type your message to chat, /help for commands, Ctrl+C to exit.[/dim]")
        self._console.print()

    def show_goodbye(self) -> None:
        """Print the goodbye message on exit."""
        self._console.print("[dim]Goodbye.[/dim]")

    def show_interrupted(self) -> None:
        self._console.print("[yellow]⚡ Run interrupted[/yellow]")

    # ── history replay ──────────────────────────────────────────────

    def replay_history(self, messages: list) -> None:
        """Render a conversation history loaded by /resume or /list.

        Skips the initial ``system`` message (the agent prompt); renders every
        user / assistant / tool message in sequence so the user can see what
        was said before.
        """
        if not messages:
            return

        self._console.print()
        self._console.print("[dim]── History replay ──[/dim]")
        self._console.print()

        for m in messages:
            role = m.role if hasattr(m, "role") else m.get("role", "")
            content = m.content if hasattr(m, "content") else m.get("content", "")
            tool_calls = m.tool_calls if hasattr(m, "tool_calls") else m.get("tool_calls", [])
            tool_call_id = m.tool_call_id if hasattr(m, "tool_call_id") else m.get("tool_call_id", "")

            if role == "system":
                continue

            if role == "user":
                self._console.print(f"[bold cyan]❯[/bold cyan] {content}")
                self._console.print()

            elif role == "assistant":
                if content:
                    self._console.print(Markdown(content))
                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        name = func.get("name", "?")
                        args_str = func.get("arguments", "{}")
                        self._console.print(
                            f"  [dim]🔧 [bold]{name}[/bold][/dim]"
                        )
                        try:
                            import json as _json
                            args_obj = _json.loads(args_str) if isinstance(args_str, str) else args_str
                            for k, v in args_obj.items():
                                val_str = str(v)
                                if len(val_str) > 80:
                                    val_str = val_str[:80] + "..."
                                self._console.print(f"    [dim]{k}:[/dim] {val_str}")
                        except Exception:
                            if args_str:
                                self._console.print(f"    [dim]{args_str}[/dim]")
                self._console.print()

            elif role == "tool":
                truncated = content if len(content) <= 300 else content[:300] + "..."
                self._console.print(
                    Panel(
                        truncated,
                        title=f"[dim]tool ⟵ {tool_call_id[:20]}...[/dim]",
                        border_style="dim",
                        expand=False,
                    )
                )

        self._console.print("[dim]── End of history ──[/dim]")
        self._console.print()

