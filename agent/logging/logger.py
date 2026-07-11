"""AgentLogger: structured JSON Lines logging for agent runs.

Each session writes to its own file: workspace/logs/{session_id}.jsonl
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
    """

    def __init__(self, logs_dir: Path, session_id: str) -> None:
        self._file = logs_dir / f"{session_id}.jsonl"
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, **kwargs: Any) -> None:
        """Append a JSON line to the log file. ``ts`` is added automatically."""
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
