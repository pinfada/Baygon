import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel

FULL_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
      broken:
        type: metrics
        plugin: nowhere.to.be:Found
    environments:
      development: {}
      staging: {}
      production: {}
    ai:
      default: offline
      providers:
        offline:
          type: ai
          plugin: baygon_plugins.offline_ai:OfflineAI
    permissions:
      deploy: true
      production: true
    """
)


class KernelTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "baygon.yaml").write_text(FULL_YAML, encoding="utf-8")

    def test_lifecycle_loads_plugins_and_isolates_failures(self) -> None:
        kernel = Kernel.start(self.dir)
        self.assertTrue(kernel.ready)
        capabilities = kernel.capabilities()
        self.assertIn("deployment", capabilities)
        self.assertIn("repository", capabilities)
        self.assertIn("ai", capabilities)
        # The broken provider is reported but does not stop the core.
        self.assertIn("broken", kernel.plugins.failures)
        self.assertNotIn("metrics", capabilities)

    def test_run_records_history(self) -> None:
        kernel = Kernel.start(self.dir)
        result = kernel.run("deploy to staging")
        self.assertTrue(result.success)
        entries = kernel.history()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["intent"], "DeployProject")
        self.assertEqual(entry["status"], "success")
        self.assertIn("date", entry)
        self.assertIn("user", entry)
        self.assertIn("plan", entry)

    def test_ai_step_uses_declared_model_and_stays_optional(self) -> None:
        kernel = Kernel.start(self.dir)
        plan = kernel.plan("analyse l'incident en staging")
        self.assertIn("ai", [step.capability for step in plan.steps])
        # Collection steps fail (no logs/metrics provider) before AI runs;
        # the failure is structured, Baygon itself never crashes.
        result = kernel.execute(plan)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.failure)


if __name__ == "__main__":
    unittest.main()
