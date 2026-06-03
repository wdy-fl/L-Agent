"""Built-in tools registry and approval configuration."""

from agent.tools.builtin.file_ops import (
    list_directory_tool,
    read_file_tool,
    search_file_tool,
    write_file_tool,
)
from agent.tools.builtin.terminal import terminal_tool
from agent.tools.builtin.think import think_tool
from agent.tools.builtin.web import web_fetch_tool, web_search_tool
from agent.tools.registry import ToolRegistry

ALL_BUILTIN_TOOLS = [
    think_tool,
    read_file_tool,
    write_file_tool,
    list_directory_tool,
    search_file_tool,
    terminal_tool,
    web_search_tool,
    web_fetch_tool,
]

AUTO_APPROVE_TOOLS = frozenset({
    "think",
    "read_file",
    "list_directory",
    "search_file",
    "web_search",
    "web_fetch",
})

ALWAYS_CONFIRM_TOOLS = frozenset({
    "terminal",
    "write_file",
})


def create_builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in ALL_BUILTIN_TOOLS:
        registry.register(tool)
    return registry
