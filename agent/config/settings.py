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
class StorageSettings:
    db_path: str = "workspace/timeline.db"


@dataclass
class ApprovalSettings:
    auto_approve: list[str] = field(default_factory=lambda: ["think", "read_file", "list_directory"])
    always_confirm: list[str] = field(default_factory=lambda: ["terminal", "write_file"])


@dataclass
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    approval: ApprovalSettings = field(default_factory=ApprovalSettings)

def load_settings(config_path: Path) -> Settings:
    """加载配置文件，config_path 必须显式指定；文件不存在时抛出 FileNotFoundError。"""
    if not config_path.exists():
        raise FileNotFoundError(config_path)

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    settings = _parse(data)

    if not settings.llm.api_key:
        raise RuntimeError(
            "llm.api_key is required. Set it in workspace/config.yaml"
        )

    return settings


def _parse(data: dict[str, Any]) -> Settings:
    llm_data = data.get("llm", {})
    budget_data = data.get("budget", {})
    storage_data = data.get("storage", {})
    approval_data = data.get("approval", {})

    return Settings(
        llm=LLMSettings(**{k: v for k, v in llm_data.items() if k in LLMSettings.__dataclass_fields__}),
        budget=BudgetSettings(**{k: v for k, v in budget_data.items() if k in BudgetSettings.__dataclass_fields__}),
        storage=StorageSettings(**{k: v for k, v in storage_data.items() if k in StorageSettings.__dataclass_fields__}),
        approval=ApprovalSettings(**{k: v for k, v in approval_data.items() if k in ApprovalSettings.__dataclass_fields__}),
    )
