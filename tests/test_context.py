import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel

CONTEXT_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
      description: A demo project
      language: python
    providers:
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
      secrets:
        type: secrets
        plugin: baygon_plugins.env_secrets:EnvSecrets
        options:
          prefix: DEMO_
    environments:
      development: {}
      staging: {}
      production: {}
    observability:
      logs: logging
      metrics: monitoring
    commands:
      deploy: "make deploy"
      test: "make test"
    permissions:
      deploy: true
      ssh: false
    """
)


class ContextEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(CONTEXT_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        self.context = self.kernel.context()

    def test_project_and_environments(self) -> None:
        self.assertEqual(self.context["project"]["name"], "demo")
        self.assertEqual(self.context["project"]["language"], "python")
        self.assertEqual(
            self.context["environments"], ["development", "production", "staging"]
        )

    def test_providers_and_capabilities_described(self) -> None:
        names = [p["name"] for p in self.context["providers"]]
        self.assertEqual(names, ["cloud", "secrets"])
        self.assertEqual(
            self.context["capabilities"]["deployment"][0]["state"], "ACTIVE"
        )

    def test_secret_values_never_included(self) -> None:
        # The context says where secrets are managed, never what they are.
        import json

        self.assertNotIn("DEMO_", json.dumps(self.context).replace("prefix", ""))
        secrets_provider = self.context["providers"][1]
        self.assertNotIn("options", secrets_provider)

    def test_permissions_and_ai_availability(self) -> None:
        self.assertEqual(self.context["permissions"], {"deploy": True, "ssh": False})
        self.assertFalse(self.context["ai"]["available"])
        self.assertEqual(self.context["commands"], ["deploy", "test"])


if __name__ == "__main__":
    unittest.main()
