"""CLI entry point: typer app + asyncio bootstrap."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from agent.cli.loop import CLILoop
from agent.config.settings import load_settings

app = typer.Typer(add_completion=False)

CONFIG_PATH = Path("workspace/config.yaml")


@app.command()
def main() -> None:
    """L-Agent CLI - Interactive AI Agent."""
    try:
        settings = load_settings(CONFIG_PATH)
    except FileNotFoundError:
        print(f"错误: 缺少配置文件 {CONFIG_PATH}，请参照 config.yaml.example 创建。")
        raise typer.Exit(1)

    cli_loop = CLILoop(settings)
    asyncio.run(cli_loop.start())


if __name__ == "__main__":
    app()
