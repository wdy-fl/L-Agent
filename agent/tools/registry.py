from __future__ import annotations

from typing import Any

from agent.tools.base import ToolSpec


class ToolRegistry:
    """Manages tool registration and lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool_spec: ToolSpec) -> None:
        self._tools[tool_spec.name] = tool_spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for spec in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters_schema,
                },
            })
        return schemas
