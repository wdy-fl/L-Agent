"""Built-in terminal tool: execute shell commands with timeout."""

from __future__ import annotations

import subprocess

from agent.tools.base import ToolSpec


def _terminal_handler(command: str, timeout: int = 120, cwd: str | None = None) -> str:
    # stdin=DEVNULL prevents interactive commands (e.g. cmd's `date` builtin on
    # Windows, which prompts for a new date) from blocking forever on inherited
    # terminal input — they read EOF and exit instead of hanging until timeout.
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
        )
        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        parts.append(f"[exit_code: {result.returncode}]")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Command timed out after {timeout}s: {command}")


terminal_tool = ToolSpec(
    name="terminal",
    description="Execute a shell command and return stdout, stderr, and exit code. Use for running builds, tests, git commands, etc.",
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 120."},
            "cwd": {"type": "string", "description": "Working directory for the command."},
        },
        "required": ["command"],
    },
    handler=_terminal_handler,
)
