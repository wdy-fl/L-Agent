from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.context import RunContext

from agent.core.lifecycle import HookPhase


class Step(ABC):
    """Base class for lifecycle steps."""

    name: str
    phase: HookPhase

    def __init__(self, name: str, phase: HookPhase) -> None:
        self.name = name
        self.phase = phase

    @abstractmethod
    async def run(self, ctx: RunContext) -> None:
        """Execute the step."""
        ...
