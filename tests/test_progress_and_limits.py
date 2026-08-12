"""TDD — progress feedback (EF-020) and a rate limiter that stays bounded.

EF-020: a command that needs an AI model must show progress rather than
go silent until the answer is ready. Progress is written on the error
stream so the structured result on standard output stays machine
readable.

ENF-011 / robustness: the API throttle keeps one window per client. A
long-running server must not accumulate one forever.
"""

import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell.api import RateLimiter
from baygon.shell.cli import attach_progress

PROGRESS_YAML = textwrap.dedent(
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
        plugin: tests.helpers:FakeDeployment
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


class ProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(PROGRESS_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        self.stream = io.StringIO()

    def test_each_step_reports_progress_while_it_runs(self) -> None:
        attach_progress(self.kernel, self.stream)
        result = self.kernel.run("analyse la production")
        self.assertTrue(result.success)

        output = self.stream.getvalue()
        # The AI step is the slow one: the user must see it start.
        self.assertIn("ai.complete", output)
        self.assertIn("logs.fetch", output)
        # Progress is counted, so the wait has a visible end.
        self.assertIn("4/4", output)

    def test_progress_reports_the_outcome_of_each_step(self) -> None:
        attach_progress(self.kernel, self.stream)
        self.kernel.run("analyse la production")
        self.assertIn("ok", self.stream.getvalue())

    def test_progress_reports_a_failure(self) -> None:
        attach_progress(self.kernel, self.stream)
        # No 'storage' provider is declared: the step fails.
        self.kernel.run("montre-moi les fichiers")
        self.assertIn("failed", self.stream.getvalue())

    def test_progress_never_writes_to_standard_output(self) -> None:
        """Standard output carries the machine-readable result only."""
        stdout = io.StringIO()
        attach_progress(self.kernel, self.stream)
        with redirect_stdout(stdout):
            self.kernel.run("analyse la production")
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(self.stream.getvalue())

    def test_a_broken_progress_stream_never_breaks_the_execution(self) -> None:
        class BrokenStream(io.StringIO):
            def write(self, _: str) -> int:
                raise OSError("broken pipe")

        attach_progress(self.kernel, BrokenStream())
        self.assertTrue(self.kernel.run("analyse la production").success)


class FakeClock:
    """Controllable monotonic clock: no test ever sleeps for a minute."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimiterTest(unittest.TestCase):
    def test_requests_are_allowed_up_to_the_limit(self) -> None:
        limiter = RateLimiter(3)
        self.assertEqual([limiter.allow("1.2.3.4") for _ in range(4)],
                         [True, True, True, False])

    def test_clients_are_throttled_independently(self) -> None:
        limiter = RateLimiter(1)
        self.assertTrue(limiter.allow("1.2.3.4"))
        self.assertFalse(limiter.allow("1.2.3.4"))
        self.assertTrue(limiter.allow("5.6.7.8"))

    def test_the_window_slides(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(1, clock=clock)
        self.assertTrue(limiter.allow("1.2.3.4"))
        self.assertFalse(limiter.allow("1.2.3.4"))
        clock.advance(61)
        self.assertTrue(limiter.allow("1.2.3.4"))

    def test_clients_gone_quiet_are_forgotten(self) -> None:
        """One window per client kept forever is a memory leak."""
        clock = FakeClock()
        limiter = RateLimiter(10, clock=clock)
        for index in range(200):
            limiter.allow(f"10.0.0.{index}")
        self.assertEqual(len(limiter.tracked_clients()), 200)

        clock.advance(120)
        limiter.allow("5.6.7.8")

        self.assertEqual(limiter.tracked_clients(), ["5.6.7.8"])

    def test_tracked_clients_stay_bounded_under_a_flood(self) -> None:
        """A flood of distinct addresses must not grow memory without end."""
        limiter = RateLimiter(10, max_clients=50)
        for index in range(2000):
            limiter.allow(f"10.{index // 65536}.{index // 256 % 256}.{index % 256}")
        self.assertLessEqual(len(limiter.tracked_clients()), 50)

    def test_a_client_that_keeps_knocking_is_never_evicted(self) -> None:
        limiter = RateLimiter(2, max_clients=8)
        self.assertTrue(limiter.allow("attacker"))
        self.assertTrue(limiter.allow("attacker"))
        for index in range(200):
            limiter.allow(f"10.0.0.{index}")
            self.assertFalse(
                limiter.allow("attacker"),
                "eviction must never hand a busy client a fresh quota",
            )


if __name__ == "__main__":
    unittest.main()
