"""TDD — real observability adapters: Loki (logs) and Prometheus (metrics).

Baygon consults logs and metrics where they already live (EF-007) and
stores nothing. Both adapters use an injectable transport, faked here.
"""

import unittest
from typing import Any

from baygon_plugins.loki_logs import LokiLogs
from baygon_plugins.prometheus_metrics import PrometheusMetrics


class FakeLoki(LokiLogs):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requested: list[tuple[str, dict[str, Any]]] = []
        self.payload: Any = {"data": {"result": []}}

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        self.requested.append((path, params))
        return self.payload


class FakePrometheus(PrometheusMetrics):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requested: list[tuple[str, dict[str, Any]]] = []
        self.payloads: list[Any] = []

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        self.requested.append((path, params))
        return self.payloads.pop(0)


class LokiLogsTest(unittest.TestCase):
    def test_fetch_queries_the_environment_stream_and_flattens_lines(self) -> None:
        adapter = FakeLoki({"url": "http://loki:3100", "queries": {"production": '{env="prod"}'}})
        adapter.payload = {
            "data": {
                "result": [
                    {"values": [["2000", "second line"], ["1000", "first line"]]},
                    {"values": [["1500", "middle line"]]},
                ]
            }
        }
        lines = adapter.fetch("production", since_hours=2)
        self.assertEqual(lines, ["first line", "middle line", "second line"])
        path, params = adapter.requested[0]
        self.assertEqual(path, "/loki/api/v1/query_range")
        self.assertEqual(params["query"], '{env="prod"}')
        self.assertLess(int(params["start"]), int(params["end"]))

    def test_environment_without_declared_query_returns_empty(self) -> None:
        adapter = FakeLoki({"url": "http://loki:3100", "queries": {}})
        self.assertEqual(adapter.fetch("staging"), [])
        self.assertEqual(adapter.requested, [])


class PrometheusMetricsTest(unittest.TestCase):
    def test_fetch_runs_each_declared_query_with_environment_substituted(self) -> None:
        adapter = FakePrometheus({
            "url": "http://prom:9090",
            "queries": {
                "latency_ms": 'latency{env="{environment}"}',
                "error_rate": 'errors{env="{environment}"}',
            },
        })
        adapter.payloads = [
            {"data": {"result": [{"value": [1234, "48.5"]}]}},
            {"data": {"result": [{"value": [1234, "0.002"]}]}},
        ]
        metrics = adapter.fetch("production")
        self.assertEqual(metrics, {"latency_ms": 48.5, "error_rate": 0.002})
        queries = sorted(params["query"] for _, params in adapter.requested)
        self.assertEqual(queries, ['errors{env="production"}', 'latency{env="production"}'])
        self.assertTrue(all(path == "/api/v1/query" for path, _ in adapter.requested))

    def test_metric_without_result_is_reported_as_none(self) -> None:
        adapter = FakePrometheus({"url": "http://prom:9090", "queries": {"latency_ms": "up"}})
        adapter.payloads = [{"data": {"result": []}}]
        self.assertEqual(adapter.fetch("staging"), {"latency_ms": None})


if __name__ == "__main__":
    unittest.main()
