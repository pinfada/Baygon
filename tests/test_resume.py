"""TDD — resumable executions (ENF-017).

A failed plan can be resumed: steps that already succeeded are never
re-executed — their recorded outputs are reused (chapter 9: reuse
results already available) — and execution restarts at the failed step.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from baygon.core.errors import BaygonError, ValidationRequiredError
from baygon.core.kernel import Kernel
from tests.helpers import FakeDeployment, FakeRepository

RESUME_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      git:
        type: repository
        plugin: tests.helpers:CountingRepository
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:FlakyDeployment
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


class ResumeTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(RESUME_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        self.repo = self.kernel.registry.resolve("repository")
        self.deploy = self.kernel.registry.resolve("deployment")

    def test_executor_skips_completed_steps_and_reuses_outputs(self) -> None:
        plan = self.kernel.plan("deploy to staging")
        completed = {"1": {"sha": "cached123", "author": "x", "subject": "y"}}
        result = self.kernel.executor.execute(plan, completed=completed)
        self.assertTrue(result.success)
        # Step 1 was never re-executed; its cached output fed step 2.
        self.assertEqual(self.repo.calls, 0)
        _, deploy_params = self.deploy.calls[0]
        self.assertEqual(deploy_params["context"]["1"]["sha"], "cached123")

    def test_resume_restarts_at_the_failed_step(self) -> None:
        self.deploy.fail_next = True
        failed = self.kernel.run("deploy to staging")
        self.assertFalse(failed.success)
        self.assertEqual(self.repo.calls, 1)

        result = self.kernel.resume()
        self.assertTrue(result.success)
        # The repository step was not re-executed on resume.
        self.assertEqual(self.repo.calls, 1)
        # The deployment received the recorded output of step 1.
        _, deploy_params = self.deploy.calls[-1]
        self.assertEqual(deploy_params["context"]["1"]["sha"], "abc123")

    def test_resume_without_failed_execution_is_an_error(self) -> None:
        with self.assertRaisesRegex(BaygonError, "resume"):
            self.kernel.resume()
        self.kernel.run("deploy to staging")  # succeeds
        with self.assertRaisesRegex(BaygonError, "resume"):
            self.kernel.resume()

    def test_resume_still_requires_validation_for_sensitive_plans(self) -> None:
        self.deploy.fail_next = True
        try:
            self.kernel.run("deploy to production", approved=True)
        except ValidationRequiredError:
            self.fail("approved run should not raise")
        with self.assertRaises(ValidationRequiredError):
            self.kernel.resume()
        result = self.kernel.resume(approved=True)
        self.assertTrue(result.success)

    def test_resume_targets_a_specific_plan_id(self) -> None:
        self.deploy.fail_next = True
        failed = self.kernel.run("deploy to staging")
        plan_id = failed.plan.id
        result = self.kernel.resume(plan_id=plan_id)
        self.assertTrue(result.success)
        with self.assertRaisesRegex(BaygonError, "resume"):
            self.kernel.resume(plan_id="plan-does-not-exist")


class ResumeCliTest(unittest.TestCase):
    def test_cli_resume_after_failure(self) -> None:
        import contextlib
        import io

        from baygon.shell.cli import main

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        file = str(Path(tmp.name) / "baygon.yaml")
        Path(file).write_text(RESUME_YAML, encoding="utf-8")

        import tests.helpers as helpers

        helpers.FLAKY_FAIL_ONCE.append(True)  # first deploy fails
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["-f", file, "run", "deploy to staging"])
        self.assertEqual(code, 1)

        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(io.StringIO()):
            code = main(["-f", file, "resume"])
        self.assertEqual(code, 0)
        self.assertIn('"success": true', out2.getvalue())


if __name__ == "__main__":
    unittest.main()
