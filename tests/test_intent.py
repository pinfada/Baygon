import tempfile
import unittest
from pathlib import Path

from baygon.core.config import load_config
from baygon.core.errors import UnknownIntentError
from baygon.core.events import EventBus
from baygon.core.intent import IntentEngine, RiskLevel
from baygon.core.registry import CapabilityRegistry
from tests.helpers import FakeNotification, write_config


class IntentEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = load_config(write_config(Path(tmp.name)))
        self.registry = CapabilityRegistry(EventBus())
        self.engine = IntentEngine(self.config, self.registry)

    def test_natural_language_french_deploy(self) -> None:
        plan = self.engine.plan("Déploie le projet en staging")
        self.assertEqual(plan.intent.name, "DeployProject")
        self.assertEqual(plan.intent.parameters["environment"], "staging")

    def test_deploy_production_is_high_risk_and_requires_validation(self) -> None:
        plan = self.engine.plan("deploy to production")
        self.assertEqual(plan.risk, RiskLevel.HIGH)
        self.assertTrue(plan.requires_validation)

    def test_deploy_staging_is_medium_risk_no_validation(self) -> None:
        plan = self.engine.plan("deploy to staging")
        self.assertEqual(plan.risk, RiskLevel.MEDIUM)
        self.assertFalse(plan.requires_validation)

    def test_logs_intent_extracts_hours(self) -> None:
        plan = self.engine.plan("montre-moi les erreurs des dernières 24 heures en production")
        self.assertEqual(plan.intent.name, "ShowLogs")
        self.assertEqual(plan.steps[0].parameters["since_hours"], 24)
        self.assertEqual(plan.steps[0].parameters["environment"], "production")
        self.assertEqual(plan.risk, RiskLevel.LOW)

    def test_deterministic_same_context_same_plan(self) -> None:
        one = self.engine.plan("deploy to staging")
        two = self.engine.plan("deploy to staging")
        self.assertEqual(one.id, two.id)
        self.assertEqual(one.to_dict(), two.to_dict())

    def test_unknown_intent_raises_with_supported_list(self) -> None:
        with self.assertRaises(UnknownIntentError) as ctx:
            self.engine.plan("fais-moi un café")
        self.assertIn("DeployProject", ctx.exception.supported)

    def test_plan_is_explainable(self) -> None:
        plan = self.engine.plan("deploy to production")
        explanation = plan.explain()
        self.assertIn("DeployProject", explanation)
        self.assertIn("Reasoning:", explanation)
        self.assertIn("validation required", explanation)

    def test_notification_step_added_only_when_capability_available(self) -> None:
        without = self.engine.plan("deploy to staging")
        self.assertEqual(len(without.steps), 2)
        self.registry.register(FakeNotification())
        with_notify = self.engine.plan("deploy to staging")
        self.assertEqual(len(with_notify.steps), 3)
        self.assertEqual(with_notify.steps[-1].capability, "notification")

    def test_project_identified_when_named_in_intent(self) -> None:
        # Chapter 9 example: "Déploie JiyuFit." -> identify the project.
        plan = self.engine.plan("Déploie Demo en staging")
        self.assertEqual(plan.intent.parameters["project"], "demo")
        self.assertIn("Project identified: demo", " / ".join(plan.reasoning))

    def test_diagnose_degrades_without_ai(self) -> None:
        plan = self.engine.plan("analyse le dernier incident en production")
        self.assertEqual(plan.intent.name, "Diagnose")
        self.assertNotIn("ai", [step.capability for step in plan.steps])
        self.assertIn("degraded", " ".join(plan.reasoning))


if __name__ == "__main__":
    unittest.main()
