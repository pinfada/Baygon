import tempfile
import unittest
from pathlib import Path

from baygon.core.config import load_config
from baygon.core.errors import ValidationRequiredError
from baygon.core.events import EventBus
from baygon.core.executor import ExecutionEngine
from baygon.core.intent import IntentEngine
from baygon.core.registry import CapabilityRegistry
from tests.helpers import (
    MINIMAL_YAML,
    BrokenDeployment,
    FakeDeployment,
    FakeLogs,
    FakeNotification,
    FakeRepository,
    write_config,
)


class ExecutorTest(unittest.TestCase):
    def _make(self, yaml_content: str = MINIMAL_YAML):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = load_config(write_config(Path(tmp.name), yaml_content))
        bus = EventBus()
        registry = CapabilityRegistry(bus)
        return config, registry, IntentEngine(config, registry), ExecutionEngine(config, registry, bus)

    def test_successful_deploy_runs_steps_in_order(self) -> None:
        config, registry, intents, executor = self._make()
        registry.register(FakeRepository())
        deploy = FakeDeployment()
        registry.register(deploy)
        notify = FakeNotification()
        registry.register(notify)

        plan = intents.plan("deploy to staging")
        result = executor.execute(plan)

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 3)
        # The deploy step received the repository result through its context.
        _, deploy_params = deploy.calls[0]
        self.assertEqual(deploy_params["context"]["1"]["sha"], "abc123")
        self.assertEqual(len(notify.messages), 1)

    def test_production_plan_suspended_without_approval(self) -> None:
        config, registry, intents, executor = self._make()
        registry.register(FakeRepository())
        registry.register(FakeDeployment())

        plan = intents.plan("deploy to production")
        with self.assertRaises(ValidationRequiredError):
            executor.execute(plan)
        result = executor.execute(plan, approved=True)
        self.assertTrue(result.success)

    def test_provider_failure_interrupts_plan_with_report(self) -> None:
        config, registry, intents, executor = self._make()
        registry.register(FakeRepository())
        registry.register(BrokenDeployment())
        notify = FakeNotification()
        registry.register(notify)

        plan = intents.plan("deploy to staging")
        result = executor.execute(plan)

        self.assertFalse(result.success)
        self.assertEqual(result.failure["step"], "2")
        self.assertIn("provider exploded", result.failure["cause"])
        self.assertIn("retry the step", result.failure["options"])
        # The plan was interrupted: the notification step never ran.
        self.assertEqual(notify.messages, [])

    def test_missing_capability_fails_step_not_baygon(self) -> None:
        config, registry, intents, executor = self._make()
        plan = intents.plan("show me the logs")
        result = executor.execute(plan)
        self.assertFalse(result.success)
        self.assertIn("logs", result.failure["cause"])

    def test_permission_denied_blocks_step(self) -> None:
        yaml_without_permissions = MINIMAL_YAML.replace(
            "permissions:\n  deploy: true\n  production: true\n", "permissions: {}\n"
        )
        config, registry, intents, executor = self._make(yaml_without_permissions)
        registry.register(FakeRepository())
        registry.register(FakeDeployment())

        plan = intents.plan("deploy to staging")
        result = executor.execute(plan)
        self.assertFalse(result.success)
        self.assertIn("not allowed", result.failure["cause"])
        self.assertIn("permissions.deploy", result.failure["options"][0])

    def test_read_only_intent_runs_without_permissions(self) -> None:
        config, registry, intents, executor = self._make()
        registry.register(FakeLogs())
        plan = intents.plan("show me the logs in staging")
        result = executor.execute(plan)
        self.assertTrue(result.success)
        self.assertEqual(result.steps[0].output, ["staging log line"])


if __name__ == "__main__":
    unittest.main()
