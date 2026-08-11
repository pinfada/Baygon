"""TDD — telling the operator what actually went wrong.

Two failures found by driving Baygon on real projects rather than on
fixtures, both of which hid the very information needed to act:

- a declared command that fails reported its exit code and its standard
  error, while the tools a project actually declares — tsc, jest,
  eslint, npm — write their diagnostics on standard *output*. `lance
  type-check` answered "exit code 2:" and nothing more;
- an observability endpoint that is out of reach took the full response
  budget to say `<urlopen error timed out>`, naming nothing. With the
  Docker stack down, asking for metrics cost 31 seconds of silence.
"""

import socket
import subprocess
import sys
import time
import unittest
from typing import Any

from baygon_plugins._http import EndpointUnreachable
from baygon_plugins._process import failure_message
from baygon_plugins.coding_agent import CodingAgent
from baygon_plugins.command_service import CommandService
from baygon_plugins.local_shell import LocalShellWorkspace
from baygon_plugins.loki_logs import LokiLogs
from baygon_plugins.prometheus_metrics import PrometheusMetrics
from baygon_plugins.tempo_traces import TempoTraces


def completed(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="x", returncode=code, stdout=out, stderr=err)


class FailureMessageTest(unittest.TestCase):
    def test_output_on_stdout_is_reported(self) -> None:
        """Where tsc, jest and eslint put their diagnostics."""
        message = failure_message("command 'type-check'", completed(2, out="src/a.ts(3,1): error TS2551"))
        self.assertIn("exit code 2", message)
        self.assertIn("TS2551", message)

    def test_output_on_stderr_is_reported(self) -> None:
        message = failure_message("restart", completed(1, err="daemon not running"))
        self.assertIn("daemon not running", message)

    def test_both_streams_are_reported_and_labelled(self) -> None:
        message = failure_message("command 'test'", completed(1, out="3 failing", err="a warning"))
        self.assertIn("stdout: 3 failing", message)
        self.assertIn("stderr: a warning", message)

    def test_silence_is_stated_rather_than_left_blank(self) -> None:
        message = failure_message("command 'x'", completed(1))
        self.assertIn("printed nothing", message)

    def test_long_output_keeps_the_end_where_the_summary_is(self) -> None:
        message = failure_message("command 'x'", completed(1, out="bruit\n" * 500 + "Found 7 errors."))
        self.assertIn("Found 7 errors.", message)
        self.assertIn("…", message)
        self.assertLess(len(message), 1200)


class CommandAdaptersReportOutputTest(unittest.TestCase):
    """The three adapters that run a subprocess, on a real failure."""

    #: Writes on stdout only, like the tools projects actually declare.
    #: Built from sys.executable: `python3` is not guaranteed on PATH.
    FAILING = f"\"{sys.executable}\" -c \"print('erreur de typage: TS2551'); raise SystemExit(2)\""

    def test_workspace_reports_what_the_command_printed(self) -> None:
        adapter = LocalShellWorkspace({"cwd": "."})
        with self.assertRaises(RuntimeError) as raised:
            adapter.execute(command="type-check", command_line=self.FAILING,
                            environment="development")
        self.assertIn("TS2551", str(raised.exception))

    def test_service_reports_what_the_command_printed(self) -> None:
        adapter = CommandService({"services": {"web": self.FAILING}, "cwd": "."})
        with self.assertRaises(RuntimeError) as raised:
            adapter.restart(service="web", environment="development")
        self.assertIn("TS2551", str(raised.exception))

    def test_coding_agent_reports_what_the_command_printed(self) -> None:
        adapter = CodingAgent({
            "command": [sys.executable, "-c", "print('agent: contexte trop long'); raise SystemExit(3)"],
            "cwd": ".",
        })
        with self.assertRaises(RuntimeError) as raised:
            adapter.fix("corrige le bug")
        self.assertIn("contexte trop long", str(raised.exception))


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ObservabilityReachabilityTest(unittest.TestCase):
    """A stack that is down must be said so, quickly and by name."""

    def _url(self) -> str:
        return f"http://127.0.0.1:{closed_port()}"

    def test_metrics_names_the_endpoint_instead_of_timing_out(self) -> None:
        url = self._url()
        adapter = PrometheusMetrics({
            "url": url, "queries": {"production": "up"}, "connect_timeout_seconds": 0.5,
        })
        started = time.monotonic()
        with self.assertRaises(EndpointUnreachable) as raised:
            adapter.fetch("production")
        self.assertIn("metrics endpoint", str(raised.exception))
        self.assertIn(url.rsplit(":", 1)[1], str(raised.exception))
        self.assertLess(time.monotonic() - started, 20)

    def test_logs_names_the_endpoint(self) -> None:
        adapter = LokiLogs({
            "url": self._url(), "queries": {"production": '{a="b"}'},
            "connect_timeout_seconds": 0.5,
        })
        with self.assertRaises(EndpointUnreachable) as raised:
            adapter.fetch("production")
        self.assertIn("logs endpoint", str(raised.exception))

    def test_traces_names_the_endpoint(self) -> None:
        adapter = TempoTraces({
            "url": self._url(), "queries": {"production": "x"},
            "connect_timeout_seconds": 0.5,
        })
        with self.assertRaises(EndpointUnreachable) as raised:
            adapter.fetch("production")
        self.assertIn("traces endpoint", str(raised.exception))

    def test_both_budgets_are_declarable(self) -> None:
        default = PrometheusMetrics({"url": "http://x"})
        self.assertEqual(default.response_timeout(), 30.0)
        self.assertEqual(default.connect_timeout(), 5.0)
        tuned = PrometheusMetrics({
            "url": "http://x", "timeout_seconds": 3, "connect_timeout_seconds": 1,
        })
        self.assertEqual(tuned.response_timeout(), 3.0)
        self.assertEqual(tuned.connect_timeout(), 1.0)

    def test_an_environment_without_a_query_never_touches_the_network(self) -> None:
        """No declared query, no reason to reach anything."""
        adapter = PrometheusMetrics({
            "url": self._url(), "queries": {}, "connect_timeout_seconds": 0.5,
        })
        self.assertEqual(adapter.fetch("production"), {})


if __name__ == "__main__":
    unittest.main()
