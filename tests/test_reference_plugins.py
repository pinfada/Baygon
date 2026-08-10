"""TDD — the reference adapters shipped in this repository's baygon.yaml.

These four adapters are the ones a newcomer actually runs: they back the
`providers` block of the repository's own baygon.yaml. ENF-016 asks for
every critical feature to be automatically testable, and the onboarding
path is critical.
"""

import io
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from baygon_plugins.console_notification import ConsoleNotification
from baygon_plugins.file_logs import FileLogs, tail_lines
from baygon_plugins.local_git import LocalGitRepository
from baygon_plugins.mock_deploy import MockDeployment
from baygon_plugins.static_metrics import StaticMetrics


@unittest.skipIf(shutil.which("git") is None, "git is not installed")
class LocalGitRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        # git marks objects read-only; on Windows that makes the plain
        # cleanup raise. The test is about the adapter, not about rmtree.
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test User")
        (self.repo / "file.txt").write_text("one\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-q", "-m", "first commit")
        self.adapter = LocalGitRepository({"path": str(self.repo)})

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True, capture_output=True, text=True,
        )

    def test_health_check_passes_inside_a_working_copy(self) -> None:
        self.assertTrue(self.adapter.health_check())

    def test_health_check_fails_outside_a_repository(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with self.assertRaises(RuntimeError):
            LocalGitRepository({"path": outside.name}).health_check()

    def test_latest_commit_reports_sha_author_and_subject(self) -> None:
        commit = self.adapter.get_latest_commit()
        self.assertEqual(commit["author"], "Test User")
        self.assertEqual(commit["subject"], "first commit")
        self.assertEqual(len(commit["sha"]), 40)

    def test_history_is_bounded_by_the_requested_limit(self) -> None:
        (self.repo / "file.txt").write_text("two\n", encoding="utf-8")
        self._git("commit", "-q", "-am", "second commit")
        self.assertEqual(len(self.adapter.history(limit=1)), 1)
        self.assertEqual(
            [entry["subject"] for entry in self.adapter.history(limit=10)],
            ["second commit", "first commit"],
        )

    def test_diff_reports_uncommitted_work(self) -> None:
        self.assertEqual(self.adapter.diff(), "")
        (self.repo / "file.txt").write_text("changed\n", encoding="utf-8")
        self.assertIn("file.txt", self.adapter.diff())

    def test_a_subject_containing_a_pipe_is_not_truncated(self) -> None:
        """The adapter joins fields with '|'; a subject may contain one."""
        (self.repo / "file.txt").write_text("three\n", encoding="utf-8")
        self._git("commit", "-q", "-am", "fix: a | b")
        self.assertEqual(self.adapter.get_latest_commit()["subject"], "fix: a | b")


class MockDeploymentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MockDeployment({})

    def test_unknown_environment_reports_an_unknown_state(self) -> None:
        self.assertEqual(
            self.adapter.status("production"),
            {"environment": "production", "state": "unknown"},
        )

    def test_deploy_records_the_environment_and_goes_live(self) -> None:
        deployment = self.adapter.deploy("staging")
        self.assertEqual(deployment["environment"], "staging")
        self.assertEqual(deployment["state"], "live")
        self.assertTrue(deployment["deployed_at"])
        self.assertEqual(self.adapter.status("staging"), deployment)

    def test_deploy_picks_the_commit_up_from_the_previous_step(self) -> None:
        deployment = self.adapter.deploy("staging", context={"1": {"sha": "abc123"}})
        self.assertEqual(deployment["commit"], "abc123")

    def test_environments_are_independent(self) -> None:
        self.adapter.deploy("staging")
        self.assertEqual(self.adapter.status("production")["state"], "unknown")

    def test_rollback_removes_the_deployment(self) -> None:
        self.adapter.deploy("staging")
        self.assertEqual(self.adapter.rollback("staging")["state"], "rolled-back")
        self.assertEqual(self.adapter.status("staging")["state"], "unknown")

    def test_rollback_without_deployment_says_so(self) -> None:
        self.assertEqual(
            self.adapter.rollback("production")["state"], "nothing-to-rollback"
        )


class StaticMetricsTest(unittest.TestCase):
    def test_declared_values_are_returned_per_environment(self) -> None:
        adapter = StaticMetrics({"values": {"production": {"latency_ms": 48}}})
        self.assertEqual(adapter.fetch("production"), {"latency_ms": 48})

    def test_undeclared_environment_returns_nothing_rather_than_failing(self) -> None:
        adapter = StaticMetrics({"values": {"production": {"latency_ms": 48}}})
        self.assertEqual(adapter.fetch("staging"), {})

    def test_adapter_without_configuration_is_still_usable(self) -> None:
        self.assertEqual(StaticMetrics({}).fetch("development"), {})


class ConsoleNotificationTest(unittest.TestCase):
    def test_the_message_is_printed_and_reported_as_delivered(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = ConsoleNotification({}).notify("deployment finished")
        self.assertIn("deployment finished", errors.getvalue())
        self.assertEqual(result, {"delivered": True, "message": "deployment finished"})

    def test_the_notification_never_pollutes_standard_output(self) -> None:
        """Standard output carries the result a program will parse.

        A notification printed there lands in the middle of the JSON of
        `baygon run` and turns a pipe into a parse error.
        """
        out, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(errors):
            ConsoleNotification({}).notify("deployment finished")
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(errors.getvalue())


class FileLogsTest(unittest.TestCase):
    """Only the tail of a log is ever shown, so only the tail is read.

    A real development log on this machine is several megabytes; a
    production one is far larger. Loading it whole to print a hundred
    lines costs seconds and the memory to match (ENF-010).
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _logs(self, text: str, limit: int = 100) -> FileLogs:
        (self.dir / "app.log").write_text(text, encoding="utf-8")
        adapter = FileLogs({"files": {"production": "app.log"}, "max_lines": limit})
        adapter.project_dir = self.dir
        return adapter

    def test_returns_the_last_lines_in_order(self) -> None:
        adapter = self._logs("".join(f"line {n}\n" for n in range(1, 51)), limit=3)
        self.assertEqual(adapter.fetch("production"), ["line 48", "line 49", "line 50"])

    def test_a_short_file_yields_all_of_its_lines(self) -> None:
        self.assertEqual(self._logs("a\nb\n", limit=100).fetch("production"), ["a", "b"])

    def test_a_last_line_without_a_newline_is_not_lost(self) -> None:
        self.assertEqual(self._logs("a\nb", limit=100).fetch("production"), ["a", "b"])

    def test_an_empty_file_yields_nothing(self) -> None:
        self.assertEqual(self._logs("", limit=100).fetch("production"), [])

    def test_windows_line_endings_are_understood(self) -> None:
        (self.dir / "app.log").write_bytes(b"a\r\nb\r\n")
        adapter = FileLogs({"files": {"production": "app.log"}, "max_lines": 100})
        adapter.project_dir = self.dir
        self.assertEqual(adapter.fetch("production"), ["a", "b"])

    def test_a_missing_file_is_not_an_error(self) -> None:
        adapter = FileLogs({"files": {"production": "absent.log"}})
        adapter.project_dir = self.dir
        self.assertEqual(adapter.fetch("production"), [])

    def test_an_undeclared_environment_yields_nothing(self) -> None:
        self.assertEqual(self._logs("a\n").fetch("staging"), [])

    def test_a_corrupt_byte_does_not_break_the_reading(self) -> None:
        """A log is read to diagnose a problem; it must not add one."""
        (self.dir / "app.log").write_bytes(b"bonjour\n\xff\xfe invalide\nfin\n")
        adapter = FileLogs({"files": {"production": "app.log"}, "max_lines": 100})
        adapter.project_dir = self.dir
        self.assertEqual(adapter.fetch("production")[-1], "fin")

    def test_reading_backwards_agrees_with_reading_everything(self) -> None:
        """The chunked walk must be indistinguishable from the naive read.

        Block boundaries are where a reverse reader goes wrong, so the
        chunk size is shrunk to force many iterations and every
        interesting limit is compared against the obvious implementation.
        """
        text = "".join(f"ligne {n} — accentué\n" for n in range(1, 201))
        path = self.dir / "app.log"
        path.write_text(text, encoding="utf-8")
        expected_all = text.splitlines()
        for chunk in (1, 2, 7, 64, 4096):
            for limit in (1, 2, 99, 200, 500):
                with self.subTest(chunk=chunk, limit=limit):
                    self.assertEqual(
                        tail_lines(path, limit, chunk_size=chunk),
                        expected_all[-limit:],
                    )

    def test_a_multi_megabyte_log_still_answers(self) -> None:
        path = self.dir / "big.log"
        line = "x" * 200
        with path.open("w", encoding="utf-8") as handle:
            for n in range(40_000):  # ~8 MB
                handle.write(f"{n} {line}\n")
        self.assertGreater(path.stat().st_size, 8_000_000)
        tail = tail_lines(path, 100)
        self.assertEqual(len(tail), 100)
        self.assertTrue(tail[-1].startswith("39999 "))
        self.assertTrue(tail[0].startswith("39900 "))


if __name__ == "__main__":
    unittest.main()
