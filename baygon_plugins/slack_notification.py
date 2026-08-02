"""Notification capability backed by a Slack incoming webhook.

The webhook URL is a secret: it is read from the environment (EF-011),
never from configuration.

    providers:
      notifier:
        type: notification
        plugin: baygon_plugins.slack_notification:SlackNotification
        options:
          webhook_env: SLACK_WEBHOOK_URL   # optional, this is the default
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from baygon.capabilities import NotificationCapability


class SlackNotification(NotificationCapability):
    identifier = "slack"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def _webhook_env(self) -> str:
        return str(self.config.get("webhook_env", "SLACK_WEBHOOK_URL"))

    def _post(self, url: str, payload: dict[str, Any]) -> None:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "baygon"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15):
            pass

    def health_check(self) -> bool:
        return bool(os.environ.get(self._webhook_env()))

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        url = os.environ.get(self._webhook_env())
        if not url:
            raise RuntimeError(f"environment variable {self._webhook_env()!r} is not set")
        self._post(url, {"text": message})
        return {"delivered": True, "channel": "slack"}
