"""Notification capability writing to standard output."""

from __future__ import annotations

from typing import Any

from baygon.capabilities import NotificationCapability


class ConsoleNotification(NotificationCapability):
    identifier = "console-notification"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        print(f"[notification] {message}")
        return {"delivered": True, "message": message}
