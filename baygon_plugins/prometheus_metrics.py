"""Metrics capability backed by Prometheus.

Baygon consults metrics where they already live and stores nothing
(EF-007). Each metric is a PromQL query declared in the provider
options; the `{environment}` placeholder is substituted at query time.

    providers:
      monitoring:
        type: metrics
        plugin: baygon_plugins.prometheus_metrics:PrometheusMetrics
        options:
          url: https://prometheus.example.com
          queries:
            latency_ms: 'histogram_quantile(0.95, http_latency{env="{environment}"})'
            error_rate: 'rate(http_errors{env="{environment}"}[5m])'
          token_env: PROMETHEUS_TOKEN   # optional
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import MetricsCapability


class PrometheusMetrics(MetricsCapability):
    identifier = "prometheus"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "baygon"}
        token = os.environ.get(str(self.config.get("token_env", "PROMETHEUS_TOKEN")))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        url = str(self.config["url"]).rstrip("/") + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        return bool(self.config.get("url"))

    def fetch(self, environment: str, **params: Any) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for name, template in (self.config.get("queries") or {}).items():
            query = str(template).replace("{environment}", environment)
            data = self._get_json("/api/v1/query", {"query": query})
            result = data.get("data", {}).get("result", [])
            if result:
                metrics[str(name)] = float(result[0]["value"][1])
            else:
                metrics[str(name)] = None
        return metrics
