"""TDD — real-world phrasings (EF-003, Article 5).

Users describe symptoms, they do not type keywords. The engine must
resolve natural requests deterministically when it can (rules, no AI —
EF-014), and fall back to AI classification for the long tail, without
ever inventing an action outside the known intents.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from baygon.core.errors import UnknownIntentError
from baygon.core.kernel import Kernel
from tests.helpers import ClassifierAI

BASE_YAML = textwrap.dedent(
    """
    version: 1
    project: {name: demo}
    providers: {}
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      migrate: "rails db:migrate"
    """
)

AI_YAML = BASE_YAML.replace(
    "providers: {}",
    "providers:\n"
    "  brain:\n"
    "    type: ai\n"
    "    plugin: tests.helpers:ClassifierAI\n"
    "    default: true",
)


class DeterministicPhrasingTest(unittest.TestCase):
    """These must work with no AI at all (EF-014)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(BASE_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def _intent(self, text: str) -> str:
        return self.kernel.plan(text).intent.name

    def test_already_working_phrasings_do_not_regress(self) -> None:
        self.assertEqual(self._intent("Pourquoi la prod est lente ?"), "Diagnose")
        self.assertEqual(
            self._intent("Y a-t-il eu des erreurs 5xx cette nuit ?"), "ShowLogs"
        )
        self.assertEqual(self._intent("Rollback la prod"), "RollbackDeployment")

    def test_symptom_reports_resolve_to_diagnosis(self) -> None:
        for text in (
            "Les utilisateurs ne peuvent plus se connecter depuis ce matin",
            "Le paiement Stripe renvoie une 500, regarde ce qui se passe",
            "La conso mémoire a doublé, tu peux voir d'où ça vient ?",
            "Le site ne répond plus",
            "L'API est tombée",
        ):
            with self.subTest(text=text):
                self.assertEqual(self._intent(text), "Diagnose")

    def test_verification_questions_resolve_to_status(self) -> None:
        for text in (
            "Est-ce que la migration de cette nuit est bien passée ?",
            "Le déploiement d'hier a-t-il réussi ?",
        ):
            with self.subTest(text=text):
                self.assertEqual(self._intent(text), "ShowStatus")

    def test_restart_requests_resolve_and_name_the_service(self) -> None:
        plan = self.kernel.plan("Redémarre le worker")
        self.assertEqual(plan.intent.name, "RestartService")
        self.assertEqual(plan.intent.parameters["service"], "worker")
        self.assertEqual(plan.steps[0].capability, "service")
        self.assertEqual(plan.steps[0].action, "restart")

    def test_restart_in_production_is_sensitive(self) -> None:
        plan = self.kernel.plan("redémarre l'api en production")
        self.assertTrue(plan.requires_validation)
        self.assertEqual(plan.intent.parameters["service"], "api")

    def test_unrelated_input_still_raises_without_ai(self) -> None:
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("fais-moi un café")


class AIFallbackTest(unittest.TestCase):
    """Long tail: AI classifies only when the rules found nothing."""

    def setUp(self) -> None:
        ClassifierAI.prompts = []
        ClassifierAI.answer = "Diagnose"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(AI_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_rules_win_and_the_model_is_never_called(self) -> None:
        plan = self.kernel.plan("Pourquoi la prod est lente ?")
        self.assertEqual(plan.intent.name, "Diagnose")
        self.assertEqual(plan.intent.resolved_by, "rules")
        self.assertEqual(ClassifierAI.prompts, [])

    def test_unmatched_input_is_classified_by_the_model(self) -> None:
        ClassifierAI.answer = "ShowMetrics"
        plan = self.kernel.plan("Le p99 du checkout est monté à 3 secondes")
        self.assertEqual(plan.intent.name, "ShowMetrics")
        self.assertEqual(plan.intent.resolved_by, "ai")
        # The plan says so: transparency (Article 8).
        self.assertIn("model", " ".join(plan.reasoning).lower())
        # The model is constrained: it only picks from the known intents.
        prompt = ClassifierAI.prompts[0]
        self.assertIn("Diagnose", prompt)
        self.assertIn("ShowMetrics", prompt)

    def test_model_answer_outside_the_known_intents_is_refused(self) -> None:
        ClassifierAI.answer = "DropDatabase"
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("Le p99 du checkout est monté à 3 secondes")

    def test_model_may_answer_none(self) -> None:
        ClassifierAI.answer = "NONE"
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("fais-moi un café")

    def test_model_failure_degrades_to_the_normal_error(self) -> None:
        def boom(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("model unreachable")

        self.kernel.registry.resolve("ai").complete = boom
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("Le p99 du checkout est monté à 3 secondes")

    def test_ai_classified_sensitive_intents_still_require_validation(self) -> None:
        # Safety does not depend on how the intent was resolved.
        ClassifierAI.answer = "RestoreProject"
        plan = self.kernel.plan("remets la base comme hier soir en production")
        self.assertEqual(plan.intent.name, "RestoreProject")
        self.assertTrue(plan.requires_validation)


class CommandServiceAdapterTest(unittest.TestCase):
    def test_restart_runs_the_declared_command(self) -> None:
        from baygon_plugins.command_service import CommandService

        class FakeService(CommandService):
            def __init__(self, config=None):
                super().__init__(config)
                self.ran: list[str] = []

            def _run(self, command_line: str) -> str:
                self.ran.append(command_line)
                return "restarted"

        adapter = FakeService({"services": {"worker": "systemctl restart app-worker"}})
        result = adapter.restart("worker", environment="production")
        self.assertEqual(adapter.ran, ["systemctl restart app-worker"])
        self.assertEqual(result["state"], "restarted")

    def test_unknown_service_lists_the_declared_ones(self) -> None:
        from baygon_plugins.command_service import CommandService

        adapter = CommandService({"services": {"worker": "true", "api": "true"}})
        with self.assertRaises(ValueError) as ctx:
            adapter.restart("database", environment="staging")
        self.assertIn("worker", str(ctx.exception))
        self.assertIn("api", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
