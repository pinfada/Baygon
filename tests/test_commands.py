"""TDD — declared project commands (chapter 6, `commands` section).

Baygon knows the project's commands without coding them: they are
declared in baygon.yaml and executed through the `workspace` capability.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.errors import UnknownIntentError, ValidationRequiredError
from baygon.core.kernel import Kernel

COMMANDS_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      shell:
        type: workspace
        plugin: tests.helpers:FakeWorkspace
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      test: "make test"
      migrate: "make migrate"
      deploy: "make deploy"
    permissions:
      deploy: true
      production: true
    """
)


class DeclaredCommandsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(COMMANDS_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_declared_command_resolves_to_run_command_intent(self) -> None:
        plan = self.kernel.plan("lance test")
        self.assertEqual(plan.intent.name, "RunCommand")
        self.assertEqual(plan.intent.parameters["command"], "test")
        self.assertEqual(plan.steps[0].capability, "workspace")
        self.assertEqual(plan.steps[0].action, "execute")
        # The command line comes from baygon.yaml, never from the core.
        self.assertEqual(plan.steps[0].parameters["command_line"], "make test")

    def test_undeclared_command_stays_unknown(self) -> None:
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("lance frobnicate")

    def test_builtin_intents_take_precedence_over_declared_commands(self) -> None:
        # "deploy" is also a declared command; the DeployProject intent wins.
        plan = self.kernel.plan("deploy to staging")
        self.assertEqual(plan.intent.name, "DeployProject")

    def test_run_command_executes_through_workspace_capability(self) -> None:
        result = self.kernel.run("run migrate")
        self.assertTrue(result.success)
        workspace = self.kernel.registry.resolve("workspace")
        self.assertEqual(workspace.executed, [("migrate", "make migrate", "development")])

    def test_command_in_production_requires_validation(self) -> None:
        plan = self.kernel.plan("run migrate in production")
        self.assertTrue(plan.requires_validation)
        with self.assertRaises(ValidationRequiredError):
            self.kernel.execute(plan)
        result = self.kernel.execute(plan, approved=True)
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
