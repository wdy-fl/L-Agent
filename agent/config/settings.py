"""Application settings loaded from YAML config file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMSettings:
    # api_base 应包含版本路径：智谱为 https://open.bigmodel.cn/api/paas/v4
    # （OpenAI 兼容，客户端只追加 /chat/completions）。
    api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    api_key: str = ""
    model: str = "glm-5.2"
    temperature: float = 0.7
    max_tokens: int = 4096
    # 开启 web 搜索：注册客户端 web_search 函数工具（调智谱 web-search-pro），
    # 需与智谱 api_base/api_key 配合使用。
    web_search: bool = False


@dataclass
class BudgetSettings:
    max_iterations: int = 25
    max_tokens: int = 200_000


@dataclass
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    config_dir: Path = field(default_factory=lambda: Path("."))


DEFAULT_CONFIG_PATHS = [
    Path("workspace/config.yaml"),
    Path.home() / ".l-agent" / "config.yaml",
]


def load_settings(config_path: Path | None = None) -> Settings:
    path = _resolve_path(config_path)
    if path is None:
        return Settings()

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    settings = _parse(data)
    settings.config_dir = path.parent
    return settings


def _resolve_path(config_path: Path | None) -> Path | None:
    if config_path and config_path.exists():
        return config_path
    for p in DEFAULT_CONFIG_PATHS:
        if p.exists():
            return p
    return None


def _parse(data: dict[str, Any]) -> Settings:
    llm_data = data.get("llm", {})
    budget_data = data.get("budget", {})

    return Settings(
        llm=LLMSettings(**{k: v for k, v in llm_data.items() if k in LLMSettings.__dataclass_fields__}),
        budget=BudgetSettings(**{k: v for k, v in budget_data.items() if k in BudgetSettings.__dataclass_fields__}),
    )
