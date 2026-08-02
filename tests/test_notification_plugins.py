"""TDD — real notification adapters: Slack webhook and SMTP e-mail.

Secrets (webhook URL, SMTP password) come from the environment
(EF-011). Transports are injectable seams, faked here.
"""

import os
import unittest
from typing import Any

from baygon_plugins.email_notification import EmailNotification
from baygon_plugins.slack_notification import SlackNotification


class FakeSlack(SlackNotification):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def _post(self, url: str, payload: dict[str, Any]) -> None:
        self.posts.append((url, payload))


class FakeEmail(EmailNotification):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.sent: list[Any] = []

    def _send(self, message: Any) -> None:
        self.sent.append(message)


class SlackNotificationTest(unittest.TestCase):
    def test_notify_posts_text_to_the_webhook_from_environment(self) -> None:
        os.environ["SLACKTEST_URL"] = "https://hooks.slack.example/T000/B000/xyz"
        self.addCleanup(os.environ.pop, "SLACKTEST_URL", None)
        adapter = FakeSlack({"webhook_env": "SLACKTEST_URL"})
        result = adapter.notify("Déploiement terminé")
        url, payload = adapter.posts[0]
        self.assertEqual(url, "https://hooks.slack.example/T000/B000/xyz")
        self.assertEqual(payload, {"text": "Déploiement terminé"})
        self.assertTrue(result["delivered"])

    def test_health_check_requires_the_webhook_variable(self) -> None:
        os.environ.pop("SLACKTEST_ABSENT", None)
        adapter = FakeSlack({"webhook_env": "SLACKTEST_ABSENT"})
        self.assertFalse(adapter.health_check())


class EmailNotificationTest(unittest.TestCase):
    def test_notify_builds_a_proper_message(self) -> None:
        adapter = FakeEmail({
            "host": "smtp.example.invalid",
            "sender": "baygon@example.invalid",
            "recipients": ["dev@example.invalid", "ops@example.invalid"],
        })
        result = adapter.notify("Le déploiement de monapp en production est terminé")
        message = adapter.sent[0]
        self.assertEqual(message["From"], "baygon@example.invalid")
        self.assertEqual(message["To"], "dev@example.invalid, ops@example.invalid")
        self.assertIn("monapp", message["Subject"])
        self.assertIn("terminé", message.get_content())
        self.assertTrue(result["delivered"])

    def test_health_check_requires_host_and_recipients(self) -> None:
        self.assertFalse(FakeEmail({}).health_check())
        self.assertTrue(
            FakeEmail({"host": "smtp.x", "sender": "a@b", "recipients": ["c@d"]}).health_check()
        )


class FailureNotificationTest(unittest.TestCase):
    """A failed execution notifies the team automatically (ENF-008)."""

    def _kernel(self, with_logs: bool = False):
        import tempfile
        import textwrap
        from pathlib import Path

        from baygon.core.kernel import Kernel

        logs_block = (
            "  logging:\n"
            "    type: logs\n"
            "    plugin: tests.helpers:FakeLogs\n"
            "    default: true\n"
            if with_logs else ""
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(
            textwrap.dedent(
                """
                version: 1
                project: {name: demo}
                providers:
                  notifier:
                    type: notification
                    plugin: tests.helpers:FakeNotification
                    default: true
                """
            )
            + logs_block
            + textwrap.dedent(
                """
                environments:
                  development: {}
                  staging: {}
                  production: {}
                """
            ),
            encoding="utf-8",
        )
        return Kernel.start(tmp.name)

    def test_failed_execution_sends_a_notification(self) -> None:
        kernel = self._kernel()
        result = kernel.run("show me the logs")  # no logs provider -> failure
        self.assertFalse(result.success)
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn(result.plan.id, notifier.messages[0])
        self.assertIn("logs", notifier.messages[0])

    def test_successful_execution_sends_no_failure_notification(self) -> None:
        kernel = self._kernel(with_logs=True)
        result = kernel.run("show me the logs")
        self.assertTrue(result.success)
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(notifier.messages, [])

    def test_notifier_failure_never_breaks_the_result(self) -> None:
        kernel = self._kernel()
        notifier = kernel.registry.resolve("notification")
        notifier.notify = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        result = kernel.run("show me the logs")  # failure + broken notifier
        self.assertFalse(result.success)  # the structured result still comes back


if __name__ == "__main__":
    unittest.main()
