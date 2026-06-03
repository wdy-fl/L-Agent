"""CLI select component: arrow-key based selection UI."""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


async def select_prompt(options: list[str], title: str = "", highlight_index: int = 0) -> int:
    """Arrow-key selection UI. Returns index of selected option, or -1 if ESC."""
    selected = [highlight_index]
    done = [False]
    result = [-1]

    kb = KeyBindings()

    @kb.add(Keys.Up)
    def _up(event):
        selected[0] = (selected[0] - 1) % len(options)

    @kb.add(Keys.Down)
    def _down(event):
        selected[0] = (selected[0] + 1) % len(options)

    @kb.add(Keys.Enter)
    def _enter(event):
        result[0] = selected[0]
        done[0] = True
        event.app.exit(result=selected[0])

    @kb.add(Keys.Escape)
    def _escape(event):
        result[0] = -1
        done[0] = True
        event.app.exit(result=-1)

    def _get_prompt() -> FormattedText:
        lines = []
        if title:
            lines.append(("bold", f"  {title}\n"))
            lines.append(("", "\n"))
        for i, opt in enumerate(options):
            if i == selected[0]:
                lines.append(("bold fg:cyan", f"  ❯ {opt}\n"))
            else:
                lines.append(("", f"    {opt}\n"))
        return FormattedText(lines)

    session: PromptSession = PromptSession(key_bindings=kb)
    try:
        return await session.prompt_async(_get_prompt, refresh_interval=0.1)
    except (EOFError, KeyboardInterrupt):
        return -1
