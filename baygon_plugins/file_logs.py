"""Logs capability reading from plain files.

Baygon consults logs where they already are; it never stores them.
The file per environment is declared in the provider options.

Only the tail of a log is ever shown, so only the tail is read: a real
development log runs to several megabytes and a production one far
beyond, and loading the whole of it to print a hundred lines would cost
seconds and the memory to match (ENF-010).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from baygon.capabilities import LogsCapability

#: Read granularity when walking a file backwards. Large enough that a
#: hundred ordinary log lines usually come back in a single block.
CHUNK_BYTES = 64 * 1024


def tail_lines(path: Path, limit: int, chunk_size: int = CHUNK_BYTES) -> list[str]:
    """The last `limit` lines of a text file, without reading it whole.

    The file is walked backwards one block at a time until enough line
    breaks have been seen. Decoding is lenient: a block boundary can
    fall inside a multi-byte character, and a damaged byte somewhere in
    a log must not break the reading — a log is consulted to diagnose a
    problem, it should not add one.
    """
    if limit <= 0:
        return []
    blocks: list[bytes] = []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        remaining = handle.tell()
        newlines = 0
        # One more break than lines wanted guarantees the last `limit`
        # lines are complete; anything earlier is dropped below.
        while remaining > 0 and newlines <= limit:
            size = min(chunk_size, remaining)
            remaining -= size
            handle.seek(remaining)
            block = handle.read(size)
            newlines += block.count(b"\n")
            blocks.append(block)
    text = b"".join(reversed(blocks)).decode("utf-8", errors="replace")
    return text.splitlines()[-limit:]


class FileLogs(LogsCapability):
    identifier = "file-logs"
    version = "0.2.0"
    author = "Baygon"
    license = "MIT"

    def fetch(self, environment: str, since_hours: int = 1, **params: Any) -> list[str]:
        files = self.config.get("files", {})
        file = files.get(environment)
        if not file:
            return []
        path = self.resolve_path(file)
        if not path.exists():
            return []
        return tail_lines(path, int(self.config.get("max_lines", 100)))
