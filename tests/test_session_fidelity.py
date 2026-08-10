"""TDD — the plan that resumes is the plan that failed.

Two guarantees are pinned down here:

- **Resume replays the session (EF-014, ENF-017).** A user who asked for
  deterministic rules only must not get an AI call back when the failed
  execution is resumed. The session options that shaped the plan travel
  with the plan.
- **A retry round keeps the chosen implementation (Registry rule 1).**
  The Dev -> QA loop re-runs a plan with feedback; the explicitly
  requested implementation must survive that copy, otherwise Baygon
  silently falls back to another provider.
"""

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.intent import Intent, Plan, RiskLevel, Step
from baygon.core.kernel import Kernel, _plan_with_feedback
from tests import helpers

SESSION_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      logging:
        type: logs
        plugin: tests.helpers:FakeLogs
        default: true
      monitoring:
        type: metrics
        plugin: tests.helpers:FakeMetrics
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:FlakyStatusDeployment
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
          plugin: tests.helpers:RecordingAI
    permissions: {}
    """
)


class ResumeReplaysTheSessionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "baygon.yaml").write_text(SESSION_YAML, encoding="utf-8")
        self.kernel = Kernel.start(self.dir)
        helpers.RecordingAI.calls = []
        helpers.FLAKY_STATUS_FAILURES.clear()

    def test_plan_records_the_session_options_that_shaped_it(self) -> None:
        plan = self.kernel.plan("analyse la production", ai=False)
        self.assertFalse(plan.ai)
        self.assertEqual(plan.to_dict()["session"], {"ai": False, "ai_model": None})

    def test_resuming_a_no_ai_execution_never_calls_the_model(self) -> None:
        helpers.FLAKY_STATUS_FAILURES.append(True)
        failed = self.kernel.run("analyse la production", ai=False)
        self.assertFalse(failed.success)
        self.assertEqual(helpers.RecordingAI.calls, [])

        resumed = self.kernel.resume()

        self.assertTrue(resumed.success)
        self.assertNotIn("ai", [step.step.capability for step in resumed.steps])
        self.assertEqual(
            helpers.RecordingAI.calls, [],
            "resume must honour the deterministic mode the user asked for (EF-014)",
        )

    def test_resuming_an_ai_execution_keeps_the_ai_step(self) -> None:
        helpers.FLAKY_STATUS_FAILURES.append(True)
        self.assertFalse(self.kernel.run("analyse la production", ai=True).success)
        resumed = self.kernel.resume()
        self.assertTrue(resumed.success)
        self.assertIn("ai", [step.step.capability for step in resumed.steps])

    def test_resume_reuses_only_steps_that_still_match_the_plan(self) -> None:
        """A recorded output belongs to one step, not to an id.

        Between the failure and the resume, baygon.yaml may have changed
        and the rebuilt plan may no longer be step-for-step identical.
        Feeding an old output into a different step would be worse than
        re-running it.
        """
        helpers.FLAKY_STATUS_FAILURES.append(True)
        self.assertFalse(self.kernel.run("analyse la production", ai=False).success)

        journal = self.dir / ".baygon" / "history.jsonl"
        entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        # The recorded step 1 now claims to be a different capability.
        entries[-1]["result"]["steps"][0]["capability"] = "storage"
        entries[-1]["result"]["steps"][0]["output"] = ["stale output"]
        journal.write_text(
            "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
        )

        resumed = self.kernel.resume()

        self.assertTrue(resumed.success)
        first = resumed.steps[0]
        self.assertFalse(first.reused, "a step that no longer matches must be re-executed")
        self.assertNotEqual(first.output, ["stale output"])


class RetryRoundKeepsTheChosenImplementationTest(unittest.TestCase):
    def test_feedback_copy_preserves_every_step_field(self) -> None:
        plan = Plan(
            id="p",
            intent=Intent(name="FixBug", parameters={}, raw_input="fix the payment bug"),
            steps=[
                Step(id="1", capability="developer", action="fix",
                     parameters={"description": "fix"}, risk=RiskLevel.MEDIUM,
                     implementation="aider"),
                Step(id="2", capability="ai", action="complete", depends_on=["1"],
                     risk=RiskLevel.LOW, implementation="second-model"),
            ],
            reasoning=["because"],
            max_rounds=3,
            feedback_step="1",
            ai=True,
            ai_model="second-model",
        )

        retried = _plan_with_feedback(plan, "2 tests failed")

        self.assertEqual(retried.steps[0].parameters["feedback"], "2 tests failed")
        self.assertEqual(
            [step.implementation for step in retried.steps], ["aider", "second-model"],
            "a retry round must not silently fall back to the default implementation",
        )
        self.assertEqual(retried.steps[1].depends_on, ["1"])
        self.assertEqual(retried.ai_model, "second-model")


if __name__ == "__main__":
    unittest.main()
