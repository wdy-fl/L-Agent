"""日志器单例访问层。

CLI 启动时调 :func:`init_logger` 一次；其余模块通过 :func:`get_logger` 拿同一个实例。
未 init 时 :func:`get_logger` 用默认目录兜底，保证测试、一次性脚本也能用。
"""

from __future__ import annotations

from pathlib import Path

from .logger import AgentLogger

_DEFAULT_LOGS_DIR = Path("workspace/logs")

_default: AgentLogger | None = None


def init_logger(
    logs_dir: Path | None = None,
    *,
    session_id: str = "",
) -> AgentLogger:
    """创建并设置进程级单例日志器。幂等：重复调用返回同一个实例。

    首次调用后可通过 ``logger.session_id = "..."`` 切换日志文件。
    """
    global _default
    if _default is not None:
        return _default
    _default = AgentLogger(
        logs_dir=logs_dir or _DEFAULT_LOGS_DIR,
        session_id=session_id,
    )
    return _default


def get_logger() -> AgentLogger:
    """返回单例日志器；未 init 时用默认目录懒创建。"""
    global _default
    if _default is None:
        _default = AgentLogger(_DEFAULT_LOGS_DIR)
    return _default


__all__ = ["AgentLogger", "init_logger", "get_logger"]
