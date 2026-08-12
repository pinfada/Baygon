"""TDD — when nothing is understood, say what *this* project can do.

Asking symbiont for "des statistiques" hit three walls at once, and the
answer mentioned none of them: no rule covers the word "statistiques";
that project declares no model, so the AI mode cannot interpret
anything either; and it has no metrics provider anyway. The refusal
listed the sixteen intentions Baygon knows — while two are possible
here.

An error that lists what is impossible is not guidance.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.errors import UnknownIntentError
from baygon.core.kernel import Kernel

NARROW_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: etroit
    providers:
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      test: "npm test"
      lint: "npm run lint"
    permissions: {}
    """
)


class StatisticsIsAWordForMetricsTest(unittest.TestCase):
    """A vocabulary gap in a deterministic rule, nothing more."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(
            NARROW_YAML.replace(
                "    environments:",
                "      monitoring:\n"
                "        type: metrics\n"
                "        plugin: tests.helpers:FakeMetrics\n"
                "        default: true\n"
                "    environments:",
            ),
            encoding="utf-8",
        )
        self.kernel = Kernel.start(tmp.name)

    def test_statistics_resolve_without_any_model(self) -> None:
        for phrase in ("donne-moi des statistiques", "montre les stats",
                       "quelles sont les statistiques de la production ?"):
            with self.subTest(phrase=phrase):
                plan = self.kernel.plan(phrase, ai=False)
                self.assertEqual(plan.intent.name, "ShowMetrics")
                self.assertEqual(plan.intent.resolved_by, "rules")


class TheRefusalGuidesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(NARROW_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def _refusal(self) -> UnknownIntentError:
        with self.assertRaises(UnknownIntentError) as raised:
            self.kernel.plan("fais-moi un café", ai=False)
        return raised.exception

    def test_it_names_what_this_project_can_actually_do(self) -> None:
        message = str(self._refusal())
        self.assertIn("ShowHistory", message, "possible here: a repository is declared")
        self.assertNotIn("BackupProject", message, "impossible here: no backup provider")

    def test_declared_commands_are_offered_too(self) -> None:
        """They are intentions by name, and the most likely thing wanted."""
        message = str(self._refusal())
        self.assertIn("lint", message)
        self.assertIn("test", message)

    def test_the_full_list_stays_available_for_programs(self) -> None:
        """The field is part of the API; only the message got shorter."""
        error = self._refusal()
        self.assertEqual(
            set(error.supported), set(self.kernel.intent_engine.supported_intents())
        )
        self.assertIn("ShowMetrics", error.supported)

    def test_it_points_at_the_command_that_explains_the_rest(self) -> None:
        self.assertIn("doctor", str(self._refusal()))

    def test_a_project_with_no_usable_intention_says_so_plainly(self) -> None:
        bare = textwrap.dedent(
            """
            version: 1
            project:
              name: nu
            providers: {}
            environments:
              development: {}
              staging: {}
              production: {}
            permissions: {}
            """
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(bare, encoding="utf-8")
        kernel = Kernel.start(tmp.name)
        with self.assertRaises(UnknownIntentError) as raised:
            kernel.plan("fais-moi un café", ai=False)
        self.assertIn("no intention is usable", str(raised.exception).lower())


class ModeAiWithoutAModelTest(unittest.TestCase):
    """Offering interpretation a project cannot perform is a false promise."""

    def test_the_page_warns_when_no_model_is_declared(self) -> None:
        from baygon.shell.web import PAGE

        self.assertIn("Aucun modèle déclaré", PAGE)
        self.assertIn("models.length", PAGE)


if __name__ == "__main__":
    unittest.main()
