"""TDD — in AI mode, a free phrasing should not need to be the right one.

Measured against a real local model, three natural requests out of five
resolved. The two that failed were not the model's fault:

- "je veux voir la charge du serveur" came back as `**ShowMetrics**`.
  The classification was right and was thrown away, because the answer
  was cleaned of quotes and dots but not of Markdown emphasis.
- "je voudrais lancer la suite de tests" came back as `NONE`. The
  declared commands were never offered to the model, so a project's own
  `test` command was unreachable by any phrasing that did not contain
  its literal name.

Article 5 is untouched: the model still chooses only from what Baygon
already knows how to do. What changes is that it can see all of it, and
that its answer is read the way models actually write.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

import tests.helpers as helpers
from baygon.core.errors import UnknownIntentError
from baygon.core.kernel import Kernel

CLASSIFY_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      monitoring:
        type: metrics
        plugin: tests.helpers:FakeMetrics
        default: true
      shell:
        type: workspace
        plugin: tests.helpers:FakeWorkspace
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    ai:
      default: model
      providers:
        model:
          type: ai
          plugin: tests.helpers:ClassifierAI
    commands:
      test: "npm test"
      lint: "npm run lint"
    permissions: {}
    """
)


class AnswerIsReadTheWayModelsWriteTest(unittest.TestCase):
    """Formatting is not meaning."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(CLASSIFY_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        helpers.ClassifierAI.prompts = []

    def _resolve_with(self, answer: str):
        helpers.ClassifierAI.answer = answer
        return self.kernel.plan("une formulation qu'aucune règle ne couvre")

    def test_markdown_emphasis_is_not_a_different_answer(self) -> None:
        """The exact case measured against the real model."""
        self.assertEqual(self._resolve_with("**ShowMetrics**").intent.name, "ShowMetrics")

    def test_backticks_bullets_and_full_stops_are_survivable(self) -> None:
        for answer in ("`ShowMetrics`", "- ShowMetrics", "ShowMetrics.", " ShowMetrics \n"):
            with self.subTest(answer=answer):
                self.assertEqual(self._resolve_with(answer).intent.name, "ShowMetrics")

    def test_case_alone_never_decides(self) -> None:
        self.assertEqual(self._resolve_with("showmetrics").intent.name, "ShowMetrics")

    def test_an_answer_outside_the_list_is_still_refused(self) -> None:
        """Article 5: Baygon never invents an action."""
        for answer in ("NONE", "DropDatabase", "**DeleteEverything**", ""):
            with self.subTest(answer=answer):
                with self.assertRaises(UnknownIntentError):
                    self._resolve_with(answer)


class DeclaredCommandsAreOfferedTest(unittest.TestCase):
    """A project's own commands are intentions too."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(CLASSIFY_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        helpers.ClassifierAI.prompts = []

    def test_the_model_is_shown_the_declared_commands(self) -> None:
        helpers.ClassifierAI.answer = "NONE"
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("peu importe")
        prompt = helpers.ClassifierAI.prompts[-1]
        self.assertIn("RunCommand:test", prompt)
        self.assertIn("RunCommand:lint", prompt)

    def test_choosing_a_command_runs_that_command(self) -> None:
        helpers.ClassifierAI.answer = "RunCommand:test"
        plan = self.kernel.plan("je voudrais lancer la suite de tests")
        self.assertEqual(plan.intent.name, "RunCommand")
        self.assertEqual(plan.intent.parameters["command"], "test")
        self.assertEqual(plan.steps[0].parameters["command_line"], "npm test")

    def test_an_undeclared_command_is_refused(self) -> None:
        helpers.ClassifierAI.answer = "RunCommand:deploy-everything"
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("peu importe")

    def test_the_model_is_told_what_each_intention_does(self) -> None:
        """Names alone leave a small model guessing from CamelCase."""
        helpers.ClassifierAI.answer = "NONE"
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("peu importe")
        prompt = helpers.ClassifierAI.prompts[-1]
        self.assertIn("ShowMetrics —", prompt)
        self.assertNotIn("ShowMetrics\n- ShowLogs", prompt, "bare names are not enough")

    def test_rules_still_win_and_cost_no_call(self) -> None:
        helpers.ClassifierAI.prompts = []
        plan = self.kernel.plan("montre les métriques")
        self.assertEqual(plan.intent.resolved_by, "rules")
        self.assertEqual(helpers.ClassifierAI.prompts, [])


if __name__ == "__main__":
    unittest.main()
