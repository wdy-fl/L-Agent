"""Built-in tools registry and approval configuration."""

from agent.tools.builtin.file_ops import (
    list_directory_tool,
    read_file_tool,
    search_file_tool,
    write_file_tool,
)
from agent.tools.builtin.terminal import terminal_tool
from agent.tools.builtin.think import think_tool
from agent.tools.builtin.web import make_web_search_tool
from agent.tools.registry import ToolRegistry

ALL_BUILTIN_TOOLS = [
    think_tool,
    read_file_tool,
    write_file_tool,
    list_directory_tool,
    search_file_tool,
    terminal_tool,
]
# web_search 需要凭据，由 factory 在 llm.web_search 开启时通过
# make_web_search_tool(api_base, api_key) 创建并注册，不放入 ALL_BUILTIN_TOOLS。

AUTO_APPROVE_TOOLS = frozenset({
    "think",
    "read_file",
    "list_directory",
    "search_file",
    "web_search",
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
