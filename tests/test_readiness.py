"""TDD — what can actually be done here, and what is missing.

`capabilities` lists providers, `context` describes configuration, and
neither answers the question an operator actually has: *what works?*
You found out an intention was impossible by attempting it — on a real
project, 14 of 16 failed and nothing said so beforehand.

Readiness answers it without contacting a single provider: it builds
each intention's plan and compares what the plan needs against what the
project declares and allows.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.core.projects import ProjectManager

READY_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: lisible
    providers:
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      test: "npm test"
      lint: "npm run lint"
    permissions:
      deploy: false
    """
)


class ReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(READY_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        self.report = self.kernel.readiness()

    def _entry(self, intent: str) -> dict:
        return next(e for e in self.report["intents"] if e["intent"] == intent)

    def test_every_supported_intention_is_accounted_for(self) -> None:
        listed = {e["intent"] for e in self.report["intents"]}
        self.assertEqual(listed, set(self.kernel.intent_engine.supported_intents()))

    def test_an_intention_whose_providers_are_declared_is_ready(self) -> None:
        entry = self._entry("ShowHistory")
        self.assertTrue(entry["ready"])
        self.assertEqual(entry["missing_capabilities"], [])

    def test_a_missing_capability_is_named(self) -> None:
        entry = self._entry("ShowLogs")
        self.assertFalse(entry["ready"])
        self.assertIn("logs", entry["missing_capabilities"])

    def test_a_refused_permission_is_named_and_told_apart(self) -> None:
        """Not declared and not allowed are different problems."""
        entry = self._entry("DeployProject")
        self.assertFalse(entry["ready"])
        self.assertEqual(entry["missing_capabilities"], [])
        self.assertIn("deploy", entry["missing_permissions"])

    def test_declared_commands_are_reported_as_usable_too(self) -> None:
        """They are intentions in their own right, by name."""
        self.assertEqual(sorted(self.report["commands"]), ["lint", "test"])

    def test_the_summary_counts_what_is_ready(self) -> None:
        ready = [e["intent"] for e in self.report["intents"] if e["ready"]]
        self.assertEqual(self.report["ready_count"], len(ready))
        self.assertEqual(self.report["total_count"], len(self.report["intents"]))
        self.assertGreater(self.report["ready_count"], 0)

    def test_providers_are_listed_with_their_state(self) -> None:
        states = {p["name"]: p["state"] for p in self.report["providers"]}
        self.assertEqual(states["git"], "ACTIVE")

    def test_a_provider_that_failed_to_load_is_reported(self) -> None:
        broken = READY_YAML.replace(
            "plugin: tests.helpers:FakeRepository", "plugin: nowhere:Absent"
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(broken, encoding="utf-8")
        report = Kernel.start(tmp.name).readiness()
        self.assertIn("git", report["failures"])

    def test_readiness_contacts_no_provider(self) -> None:
        """It answers from the configuration, so it stays instant."""
        deployment = self.kernel.registry.resolve("deployment")
        self.kernel.readiness()
        self.assertEqual(deployment.calls, [], "no provider may be called")

    def test_a_missing_capability_comes_with_what_to_declare(self) -> None:
        entry = self._entry("ShowLogs")
        self.assertTrue(entry["remedy"])
        self.assertIn("logs", " ".join(entry["remedy"]))


class ReadinessAcrossProjectsTest(unittest.TestCase):
    """The overview: several projects, one answer."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in ("un", "deux"):
            directory = root / name
            directory.mkdir()
            (directory / "baygon.yaml").write_text(
                READY_YAML.replace("name: lisible", f"name: {name}"), encoding="utf-8"
            )
        self.manager = ProjectManager.discover(root)

    def test_every_project_is_summarised(self) -> None:
        overview = self.manager.readiness()
        self.assertEqual(sorted(p["project"] for p in overview["projects"]), ["deux", "un"])
        for project in overview["projects"]:
            self.assertGreater(project["total_count"], 0)
            self.assertIn("intents", project)

    def test_a_broken_project_appears_instead_of_disappearing(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "casse").mkdir()
        (root / "casse" / "baygon.yaml").write_text("nonsense: true", encoding="utf-8")
        overview = ProjectManager.discover(root).readiness()
        self.assertIn("casse", overview["unavailable"])


if __name__ == "__main__":
    unittest.main()
