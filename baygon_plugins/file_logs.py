"""Logs capability reading from plain files.

Baygon consults logs where they already are; it never stores them.
The file per environment is declared in the provider options.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from baygon.capabilities import LogsCapability


class FileLogs(LogsCapability):
    identifier = "file-logs"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def fetch(self, environment: str, since_hours: int = 1, **params: Any) -> list[str]:
        files = self.config.get("files", {})
        file = files.get(environment)
        if not file:
            return []
        path = Path(file)
        if not path.exists():
            return []
        limit = int(self.config.get("max_lines", 100))
        return path.read_text(encoding="utf-8").splitlines()[-limit:]
