"""Notification capability backed by SMTP e-mail.

The SMTP password, when needed, is read from the environment (EF-011).

    providers:
      notifier:
        type: notification
        plugin: baygon_plugins.email_notification:EmailNotification
        options:
          host: smtp.example.com
          port: 587
          starttls: true
          sender: baygon@example.com
          recipients: [dev@example.com]
          user: baygon@example.com        # optional
          password_env: SMTP_PASSWORD     # optional
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any

from baygon.capabilities import NotificationCapability


class EmailNotification(NotificationCapability):
    identifier = "email"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def _send(self, message: EmailMessage) -> None:
        host = str(self.config["host"])
        port = int(self.config.get("port", 587))
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if self.config.get("starttls", True):
                smtp.starttls()
            user = self.config.get("user")
            password = os.environ.get(str(self.config.get("password_env", "SMTP_PASSWORD")))
            if user and password:
                smtp.login(str(user), password)
            smtp.send_message(message)

    def health_check(self) -> bool:
        return bool(
            self.config.get("host")
            and self.config.get("sender")
            and self.config.get("recipients")
        )

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        mail = EmailMessage()
        mail["From"] = str(self.config["sender"])
        mail["To"] = ", ".join(str(r) for r in self.config["recipients"])
        subject = message.splitlines()[0][:78] if message else "Notification Baygon"
        mail["Subject"] = f"[baygon] {subject}"
        mail.set_content(message)
        self._send(mail)
        return {"delivered": True, "channel": "email", "recipients": len(self.config["recipients"])}
