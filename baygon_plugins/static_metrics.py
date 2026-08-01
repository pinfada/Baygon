"""Metrics capability returning values declared in configuration.

Stands in for a real monitoring adapter (Grafana, Prometheus, ...).
"""

from __future__ import annotations

from typing import Any

from baygon.capabilities import MetricsCapability


class StaticMetrics(MetricsCapability):
    identifier = "static-metrics"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def fetch(self, environment: str, **params: Any) -> dict[str, Any]:
        values = self.config.get("values", {})
        return values.get(environment, {})
