"""TDD — Fly.io adapter for the Deployment capability.

Chapter 8's literal example: "Si demain Render est remplacé par
Fly.io : aucun changement dans Baygon." This adapter orchestrates the
specialized flyctl CLI (Baygon never deploys itself, EF-008); apps map
to environments in the provider options. Injectable command seam.
"""

import unittest
from typing import Any

from baygon_plugins.fly_deploy import FlyDeployment


class FakeFly(FlyDeployment):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.commands: list[list[str]] = []
        self.outputs: list[str] = []

    def _flyctl(self, args: list[str]) -> str:
        self.commands.append(args)
        return self.outputs.pop(0) if self.outputs else "{}"


def _adapter() -> FakeFly:
    return FakeFly({"apps": {"staging": "jiyufit-stg", "production": "jiyufit-prod"}})


class FlyDeploymentTest(unittest.TestCase):
    def test_deploy_targets_the_mapped_app(self) -> None:
        adapter = _adapter()
        adapter.outputs = ["deployed"]
        result = adapter.deploy("staging")
        self.assertEqual(
            adapter.commands[0], ["deploy", "--app", "jiyufit-stg", "--remote-only"]
        )
        self.assertEqual(result["environment"], "staging")
        self.assertEqual(result["state"], "deployed")

    def test_status_parses_flyctl_json(self) -> None:
        adapter = _adapter()
        adapter.outputs = ['{"Name": "jiyufit-prod", "Status": "running"}']
        status = adapter.status("production")
        self.assertEqual(
            adapter.commands[0], ["status", "--app", "jiyufit-prod", "--json"]
        )
        self.assertEqual(status["state"], "running")

    def test_unmapped_environment_raises(self) -> None:
        adapter = _adapter()
        with self.assertRaisesRegex(ValueError, "development"):
            adapter.deploy("development")

    def test_rollback_uses_flyctl_releases(self) -> None:
        adapter = _adapter()
        adapter.outputs = ["rolled back"]
        result = adapter.rollback("staging")
        self.assertEqual(
            adapter.commands[0], ["releases", "rollback", "--app", "jiyufit-stg", "--yes"]
        )
        self.assertEqual(result["state"], "rolled-back")


if __name__ == "__main__":
    unittest.main()
