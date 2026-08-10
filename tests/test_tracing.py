"""TDD — Tracing capability (EF-007, chapter 8 "Capacités minimales").

Chapter 8 lists Tracing among the minimal capabilities and EF-007
requires Baygon to be able to consult traces. Like logs and metrics,
traces are consulted where they already live: Baygon stores nothing.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from baygon.capabilities import CAPABILITY_CONTRACTS, TracesCapability
from baygon.core.kernel import Kernel
from baygon_plugins.tempo_traces import TempoTraces

TRACING_YAML = textwrap.dedent(
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
      tracing:
        type: traces
        plugin: tests.helpers:FakeTraces
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    permissions: {}
    """
)

def _without_provider(yaml_text: str, name: str) -> str:
    """Same configuration minus one provider block."""
    lines = yaml_text.splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines) if line.strip() == f"{name}:")
    end = next(
        index for index in range(start + 1, len(lines))
        if lines[index].strip() and not lines[index].startswith("    ")
    )
    return "".join(lines[:start] + lines[end:])


WITHOUT_TRACING_YAML = _without_provider(TRACING_YAML, "tracing")


class FakeTempo(TempoTraces):
    """Tempo adapter with the transport seam faked, like the Loki tests."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requested: list[tuple[str, dict[str, Any]]] = []
        self.payload: Any = {"traces": []}

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        self.requested.append((path, params))
        return self.payload


class TracesContractTest(unittest.TestCase):
    def test_traces_is_a_registered_capability_contract(self) -> None:
        self.assertIs(CAPABILITY_CONTRACTS["traces"], TracesCapability)
        self.assertEqual(TracesCapability.capability, "traces")


class TempoTracesTest(unittest.TestCase):
    def test_fetch_queries_the_environment_selector_and_normalizes_traces(self) -> None:
        adapter = FakeTempo(
            {"url": "http://tempo:3200", "queries": {"production": 'service.name="api"'}}
        )
        adapter.payload = {
            "traces": [
                {
                    "traceID": "aaa",
                    "rootServiceName": "api",
                    "rootTraceName": "GET /orders",
                    "durationMs": 512,
                    "startTimeUnixNano": "1700000000000000000",
                },
                {
                    "traceID": "bbb",
                    "rootServiceName": "api",
                    "rootTraceName": "GET /health",
                    "durationMs": 3,
                    "startTimeUnixNano": "1700000001000000000",
                },
            ]
        }
        traces = adapter.fetch("production", since_hours=2)

        # Slowest first: a diagnosis starts with what hurts.
        self.assertEqual([t["id"] for t in traces], ["aaa", "bbb"])
        self.assertEqual(traces[0]["service"], "api")
        self.assertEqual(traces[0]["name"], "GET /orders")
        self.assertEqual(traces[0]["duration_ms"], 512.0)

        path, params = adapter.requested[0]
        self.assertEqual(path, "/api/search")
        self.assertEqual(params["q"], 'service.name="api"')
        self.assertLess(int(params["start"]), int(params["end"]))

    def test_environment_without_declared_query_returns_empty(self) -> None:
        adapter = FakeTempo({"url": "http://tempo:3200", "queries": {}})
        self.assertEqual(adapter.fetch("staging"), [])
        self.assertEqual(adapter.requested, [])

    def test_health_check_requires_a_declared_url(self) -> None:
        self.assertFalse(TempoTraces({}).health_check())
        self.assertTrue(TempoTraces({"url": "http://tempo:3200"}).health_check())

    def test_slow_only_filters_out_fast_traces(self) -> None:
        adapter = FakeTempo(
            {
                "url": "http://tempo:3200",
                "queries": {"production": 'service.name="api"'},
                "min_duration_ms": 100,
            }
        )
        adapter.payload = {
            "traces": [
                {"traceID": "slow", "durationMs": 512},
                {"traceID": "fast", "durationMs": 3},
            ]
        }
        self.assertEqual([t["id"] for t in adapter.fetch("production")], ["slow"])


class ShowTracesIntentTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "baygon.yaml").write_text(TRACING_YAML, encoding="utf-8")
        self.kernel = Kernel.start(self.dir)

    def test_asking_for_traces_resolves_to_the_traces_capability(self) -> None:
        plan = self.kernel.plan("montre-moi les traces de la production")
        self.assertEqual(plan.intent.name, "ShowTraces")
        self.assertEqual([(s.capability, s.action) for s in plan.steps], [("traces", "fetch")])
        self.assertEqual(plan.steps[0].parameters["environment"], "production")

    def test_consulting_traces_is_read_only(self) -> None:
        plan = self.kernel.plan("affiche les traces")
        self.assertEqual(plan.risk.value, "LOW")
        self.assertFalse(plan.requires_validation)

    def test_traces_are_fetched_through_the_provider(self) -> None:
        result = self.kernel.run("montre-moi les traces de la production")
        self.assertTrue(result.success)
        self.assertEqual(result.steps[0].output[0]["service"], "checkout")


class DiagnoseWithTracesTest(unittest.TestCase):
    def _kernel(self, yaml_text: str) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_text, encoding="utf-8")
        return Kernel.start(tmp.name)

    def test_diagnosis_collects_traces_when_the_capability_is_available(self) -> None:
        plan = self._kernel(TRACING_YAML).plan("pourquoi la production est lente ?")
        self.assertIn("traces", [step.capability for step in plan.steps])
        traces_step = next(s for s in plan.steps if s.capability == "traces")
        self.assertEqual(traces_step.parameters["environment"], "production")
        self.assertIn(
            "traces", " ".join(plan.reasoning).lower(),
            "the plan must explain that traces are part of the diagnosis",
        )

    def test_diagnosis_without_tracing_provider_is_unchanged(self) -> None:
        plan = self._kernel(WITHOUT_TRACING_YAML).plan("pourquoi la production est lente ?")
        self.assertNotIn("traces", [step.capability for step in plan.steps])
        self.assertTrue(plan.steps, "the diagnosis still runs without tracing (ENF-006)")


if __name__ == "__main__":
    unittest.main()
