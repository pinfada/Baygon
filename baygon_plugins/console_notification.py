"""Notification capability writing to the terminal.

Notifications go to the **error stream**, never to standard output.
Standard output carries the machine-readable result of a command — a
notification landing in the middle of it turns `baygon run ... | jq`
into a parse error. The same rule governs the progress display
(EF-020): what a human reads and what a program reads travel on
separate streams.
"""

from __future__ import annotations

import sys
from typing import Any

from baygon.capabilities import NotificationCapability


class ConsoleNotification(NotificationCapability):
    identifier = "console-notification"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        print(f"[notification] {message}", file=sys.stderr, flush=True)
        return {"delivered": True, "message": message}
