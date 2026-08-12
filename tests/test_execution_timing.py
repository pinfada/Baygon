"""TDD — observability of every action (ENF-008).

ENF-008 requires that each important action be observable with, at
minimum: start, end, duration, success, failure and the eventual error.
Start and end existed for the plan as a whole; duration — and per-step
timing — are what this module pins down.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core import events
from baygon.core.kernel import Kernel

TIMING_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:BrokenDeployment
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      deploy: true
      production: true
    """
)

WORKING_YAML = TIMING_YAML.replace("BrokenDeployment", "FakeDeployment")


class StepTimingTest(unittest.TestCase):
    def _kernel(self, yaml_text: str = WORKING_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_text, encoding="utf-8")
        return Kernel.start(tmp.name)

    def test_every_step_reports_start_end_and_duration(self) -> None:
        result = self._kernel().run("deploy to staging")
        self.assertTrue(result.success)
        for step in result.steps:
            self.assertTrue(step.started_at, f"step {step.step.id} has no start")
            self.assertTrue(step.finished_at, f"step {step.step.id} has no end")
            self.assertGreaterEqual(step.duration_ms, 0.0)
            self.assertLessEqual(step.started_at, step.finished_at)

    def test_the_execution_reports_its_own_duration(self) -> None:
        result = self._kernel().run("deploy to staging")
        self.assertGreaterEqual(result.duration_ms, 0.0)
        # The whole is never shorter than any of its parts.
        self.assertGreaterEqual(
            result.duration_ms + 1e-6, max(step.duration_ms for step in result.steps)
        )

    def test_timing_is_part_of_the_serialized_result(self) -> None:
        payload = self._kernel().run("deploy to staging").to_dict()
        self.assertIn("duration_ms", payload)
        for step in payload["steps"]:
            self.assertIn("started_at", step)
            self.assertIn("finished_at", step)
            self.assertIn("duration_ms", step)

    def test_a_failed_step_is_timed_too(self) -> None:
        """A failure must be as observable as a success (ENF-008)."""
        result = self._kernel(TIMING_YAML).run("deploy to staging")
        self.assertFalse(result.success)
        failed = result.steps[-1]
        self.assertFalse(failed.success)
        self.assertTrue(failed.error)
        self.assertTrue(failed.started_at)
        self.assertTrue(failed.finished_at)
        self.assertGreaterEqual(failed.duration_ms, 0.0)

    def test_step_finished_event_carries_the_duration(self) -> None:
        kernel = self._kernel()
        seen: list[dict] = []
        kernel.bus.subscribe(events.STEP_FINISHED, lambda event: seen.append(event.payload))
        kernel.run("deploy to staging")
        self.assertTrue(seen)
        for payload in seen:
            self.assertIn("duration_ms", payload)
            self.assertGreaterEqual(payload["duration_ms"], 0.0)

    def test_execution_finished_event_carries_the_duration(self) -> None:
        kernel = self._kernel()
        seen: list[dict] = []
        kernel.bus.subscribe(events.EXECUTION_FINISHED, lambda event: seen.append(event.payload))
        kernel.run("deploy to staging")
        self.assertIn("duration_ms", seen[-1])

    def test_a_reused_step_is_marked_as_such_and_costs_nothing(self) -> None:
        """A resumed step was not executed: saying it took time would lie."""
        kernel = self._kernel()
        plan = kernel.plan("deploy to staging")
        completed = {"1": {"sha": "cached", "author": "x", "subject": "y"}}
        result = kernel.executor.execute(plan, completed=completed)
        reused = result.steps[0]
        self.assertTrue(reused.reused)
        self.assertEqual(reused.duration_ms, 0.0)
        self.assertFalse(result.steps[1].reused)


if __name__ == "__main__":
    unittest.main()
