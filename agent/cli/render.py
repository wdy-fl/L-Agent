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

    def stream_text(self, text: str) -> None:
        self._stream_buffer += text
        if self._live is None:
            self._live = Live(console=self._console, refresh_per_second=10)
            self._live.start()
        self._live.update(Markdown(self._stream_buffer))

    def finish_stream(self) -> None:
        if self._live is not None:
            self._live.update(Markdown(self._stream_buffer))
            self._live.stop()
            self._live = None
        self._stream_buffer = ""

    def show_reasoning(self, text: str) -> None:
        """Display the model's reasoning chain (dim panel, after the answer).

        For reasoning models like GLM-5.2 this also carries the web_search
        citation references, so it doubles as a source-transparency view.
        """
        if not text or not text.strip():
            return
        self._console.print(Panel(
            text,
            title="[dim]reasoning[/dim]",
            border_style="dim",
            expand=False,
        ))

    def show_tool_spinner(self, tool_name: str) -> None:
        self._console.print(
            Spinner("dots", text=Text(f" Running {tool_name}...", style="dim")),
            end="",
        )

    def finish_tool(self, tool_name: str, result) -> None:
        content = str(result) if result else ""
        if len(content) > 500:
            content = content[:500] + "..."
        self._console.print(Panel(
            content,
            title=f"[bold green]✓[/bold green] {tool_name}",
            border_style="green",
            expand=False,
        ))

    def show_error(self, error: Exception) -> None:
        self._console.print(Panel(
            str(error),
            title="[bold red]Error[/bold red]",
            border_style="red",
        ))

    def show_status(self, iterations: int, tokens: int, elapsed_ms: float) -> None:
        elapsed_s = elapsed_ms / 1000
        self._console.print(
            f"[dim]── {iterations} iteration(s) · {tokens} tokens · {elapsed_s:.1f}s[/dim]"
        )

    def show_interrupted(self) -> None:
        self._console.print("[yellow]⚡ Run interrupted[/yellow]")

    def show_run_failed(self) -> None:
        self._console.print("[red]✗ Run failed[/red]")
