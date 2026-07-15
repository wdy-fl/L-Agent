"""AgentLogger: structured JSON Lines logging for agent runs.

Each session writes to its own file: workspace/logs/{session_id}.jsonl

Session ID is mutable so /new can switch log files without recreating the logger.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgentLogger:
    """Write structured log entries as JSON Lines to a session-scoped file.

    Usage:
        logger = AgentLogger(Path("workspace/logs"), "sess_abc")
        logger.log(event="run.start", run_id="r1", input="hello")
        logger.session_id = "sess_xyz"  # switch log file for new session
    """

    def __init__(self, logs_dir: Path, session_id: str = "") -> None:
        self._logs_dir = Path(logs_dir)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id
        self._file = self._logs_dir / f"{session_id}.jsonl" if session_id else self._logs_dir / "_default.jsonl"

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value
        self._file = self._logs_dir / f"{value}.jsonl"

    def log(self, **kwargs: Any) -> None:
        """Append a JSON line to the log file. ``ts`` is added automatically."""
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
