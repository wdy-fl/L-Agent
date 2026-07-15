from enum import Enum


class HookPhase(str, Enum):
    before_run = "before_run"
    before_model = "before_model"
    after_model = "after_model"
    before_tool = "before_tool"
    after_tool = "after_tool"
    after_run = "after_run"

    @property
    def is_run_level(self) -> bool:
        return self in (HookPhase.before_run, HookPhase.after_run)

    @property
    def is_iteration_level(self) -> bool:
        return not self.is_run_level


class ActionName(str, Enum):
    model_call = "model_call"
    tool_call = "tool_call"
