"""CLI approval interaction: tool approval with select UI."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from agent.cli.select import select_prompt
from agent.events import ApprovalRequest


APPROVAL_OPTIONS = ["Yes", "No", "Always allow"]


class ApprovalHandler:
    """Handles tool approval requests via select UI."""

    def __init__(self, console: Console, auto_approve: set[str] | None = None) -> None:
        self._console = console
        self._auto_approve = auto_approve or set()

    async def prompt(self, req: ApprovalRequest) -> bool:
        if req.tool_name in self._auto_approve:
            return True

        self._console.print(Panel(
            f"[bold]Tool:[/bold] {req.tool_name}\n"
            f"[bold]Args:[/bold] {req.arguments}\n"
            f"[bold]Risk:[/bold] {req.risk_level}",
            title="Tool Approval",
            border_style="yellow",
        ))

        choice = await select_prompt(APPROVAL_OPTIONS)
        if choice == 0:  # Yes
            return True
        elif choice == 2:  # Always allow
            self._auto_approve.add(req.tool_name)
            return True
        return False
