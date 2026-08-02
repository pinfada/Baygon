"""TDD — the Dev → QA loop: "Résous le bug de paiement".

The FixBug intent chains: developer.fix (a coding agent, orchestrated
like any specialized tool) → workspace.execute of the declared `test`
command (Baygon's independent QA check) → success notification.
When QA fails, the kernel retries the whole plan with the failure
report injected as feedback to the developer step — bounded rounds,
every attempt audited, final failure notified (chapter 9 error flow).
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.intent import RiskLevel
from baygon.core.kernel import Kernel

FIXBUG_YAML = textwrap.dedent(
    """
    version: 1
    project: {name: jiyufit}
    providers:
      dev:
        type: developer
        plugin: tests.helpers:LoopDevAgent
        default: true
      shell:
        type: workspace
        plugin: tests.helpers:GatedWorkspace
        default: true
      notifier:
        type: notification
        plugin: tests.helpers:FakeNotification
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      test: "npm test"
    """
)


class FixBugIntentTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = FIXBUG_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def setUp(self) -> None:
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update({"attempts": 0, "fixed_after": 1, "feedbacks": []})

    def test_fix_intent_builds_the_dev_qa_notify_chain(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("Résous le bug de paiement")
        self.assertEqual(plan.intent.name, "FixBug")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps],
            [("developer", "fix"), ("workspace", "execute"), ("notification", "notify")],
        )
        self.assertIn("paiement", plan.steps[0].parameters["description"])
        # QA runs the test command declared in baygon.yaml.
        self.assertEqual(plan.steps[1].parameters["command_line"], "npm test")
        self.assertEqual(plan.risk, RiskLevel.MEDIUM)  # code changes are reversible
        self.assertEqual(plan.max_rounds, 3)

    def test_first_attempt_success_notifies_validation(self) -> None:
        kernel = self._kernel()
        result = kernel.run("corrige le bug de paiement")
        self.assertTrue(result.success)
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("validé", notifier.messages[0])

    def test_qa_failure_feeds_back_to_the_developer_and_retries(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 2  # first fix is wrong, second works
        kernel = self._kernel()
        result = kernel.run("Résous le bug de paiement")
        self.assertTrue(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 2)
        feedbacks = helpers.FIXBUG_STATE["feedbacks"]
        self.assertIsNone(feedbacks[0])          # round 1: no feedback yet
        self.assertIn("tests failed", feedbacks[1])  # round 2: QA report injected

    def test_rounds_are_bounded_and_final_failure_is_notified(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 99  # never fixed
        kernel = self._kernel()
        result = kernel.run("répare le bug de paiement")
        self.assertFalse(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 3)  # max_rounds
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("failed", notifier.messages[0])

    def test_without_declared_test_command_the_plan_says_so(self) -> None:
        yaml_without = FIXBUG_YAML.replace('commands:\n  test: "npm test"\n', "")
        kernel = self._kernel(yaml_without)
        plan = kernel.plan("fix the payment bug")
        self.assertEqual([s.capability for s in plan.steps], ["developer"])
        self.assertIn("no declared 'test' command", " ".join(plan.reasoning).lower())


class CodingAgentAdapterTest(unittest.TestCase):
    def test_fix_invokes_the_agent_command_with_the_description(self) -> None:
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, config=None):
                super().__init__(config)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "patched payment handler"

        adapter = FakeAgent({"command": ["claude", "-p", "{prompt}"]})
        result = adapter.fix("Résous le bug de paiement")
        self.assertEqual(adapter.commands[0][:2], ["claude", "-p"])
        self.assertIn("paiement", adapter.commands[0][2])
        self.assertEqual(result["state"], "patched")

    def test_feedback_is_appended_to_the_prompt(self) -> None:
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, config=None):
                super().__init__(config)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "ok"

        adapter = FakeAgent({"command": ["agent", "{prompt}"]})
        adapter.fix("corrige le bug", feedback="2 tests failed: test_refund")
        self.assertIn("test_refund", adapter.commands[0][1])


if __name__ == "__main__":
    unittest.main()
