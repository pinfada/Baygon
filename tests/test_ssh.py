"""TDD — remote access through the SSH capability (EF-010).

Baygon gives access to authorized remote resources: the intention
"ouvre une console" resolves to the ssh capability, which returns the
connection command declared in configuration. The `ssh` permission
(chapter 6) gates the operation.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel

SSH_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      remote:
        type: ssh
        plugin: baygon_plugins.ssh_access:SSHAccess
        default: true
        options:
          targets:
            staging: deploy@staging.example.invalid
            production: deploy@prod.example.invalid
          options: "-p 2222"
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      ssh: true
      production: true
    """
)


class SshCapabilityTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = SSH_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def test_console_intent_resolves_to_ssh_capability(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("Ouvre une console sur staging")
        self.assertEqual(plan.intent.name, "OpenConsole")
        self.assertEqual(plan.steps[0].capability, "ssh")
        self.assertEqual(plan.steps[0].action, "command")

    def test_execution_returns_the_declared_connection_command(self) -> None:
        kernel = self._kernel()
        result = kernel.run("ouvre une console sur staging")
        self.assertTrue(result.success)
        self.assertEqual(
            result.steps[0].output["command"], "ssh -p 2222 deploy@staging.example.invalid"
        )

    def test_ssh_permission_is_required(self) -> None:
        yaml_without = SSH_YAML.replace("  ssh: true\n", "")
        kernel = self._kernel(yaml_without)
        result = kernel.run("ouvre une console sur staging")
        self.assertFalse(result.success)
        self.assertIn("ssh", result.failure["cause"])

    def test_unmapped_environment_fails_cleanly(self) -> None:
        kernel = self._kernel()
        result = kernel.run("ouvre une console")  # development, not mapped
        self.assertFalse(result.success)
        self.assertIn("development", result.failure["cause"])


if __name__ == "__main__":
    unittest.main()
