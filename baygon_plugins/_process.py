"""Reporting what a command actually said when it failed.

Shared by the adapters that run a subprocess. Not a capability
implementation and not part of the core: just the answer to a question
all three had to answer, and answered badly.

A failed command used to be reported with its exit code and its
standard error. But most of the tools a project declares — tsc, jest,
eslint, npm — write their diagnostics on standard *output*. The
operator was told `exit code 2:` and nothing else, while the reason sat
in a stream nobody read.
"""

from __future__ import annotations

import subprocess

#: How much of a stream to keep. Enough for a compiler's summary, small
#: enough to stay readable in a JSON result or a notification.
MAX_OUTPUT_CHARS = 800


def _tail(text: str) -> str:
    """The end of the output: where tools put their summary."""
    trimmed = text.strip()
    if len(trimmed) <= MAX_OUTPUT_CHARS:
        return trimmed
    return "…" + trimmed[-MAX_OUTPUT_CHARS:]


def failure_message(what: str, completed: subprocess.CompletedProcess[str]) -> str:
    """Why `what` failed, whichever stream carried the reason."""
    parts = [f"{what} failed with exit code {completed.returncode}"]
    for name, stream in (("stderr", completed.stderr), ("stdout", completed.stdout)):
        text = _tail(stream or "")
        if text:
            parts.append(f"{name}: {text}")
    if len(parts) == 1:
        parts.append("the command printed nothing on either stream")
    return "; ".join(parts)
