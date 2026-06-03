from agent.tools.base import ToolSpec


def _think_handler(thought: str) -> str:
    return thought


think_tool = ToolSpec(
    name="think",
    description="A tool for the model to think step by step. Returns the thought unchanged.",
    parameters_schema={
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "The thought to record.",
            },
        },
        "required": ["thought"],
    },
    handler=_think_handler,
)
