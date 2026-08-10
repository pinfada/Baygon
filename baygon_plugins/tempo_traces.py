"""Traces capability backed by Grafana Tempo (and Tempo-compatible APIs).

Baygon consults traces where they already live and stores nothing
(EF-007). Each environment maps to a search query in the provider
options; an optional bearer token comes from the environment.

    providers:
      tracing:
        type: traces
        plugin: baygon_plugins.tempo_traces:TempoTraces
        options:
          url: https://tempo.example.com
          queries:
            production: 'service.name="api" && env="prod"'
            staging: 'service.name="api" && env="stg"'
          limit: 20
          min_duration_ms: 500        # optional: keep only slow traces
          token_env: TEMPO_TOKEN      # optional

Traces come back sorted slowest first: a diagnosis starts with what
hurts.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import TracesCapability


class TempoTraces(TracesCapability):
    identifier = "tempo"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "baygon"}
        token = os.environ.get(str(self.config.get("token_env", "TEMPO_TOKEN")))
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

    def fetch(
        self, environment: str, since_hours: int = 1, **params: Any
    ) -> list[dict[str, Any]]:
        query = (self.config.get("queries") or {}).get(environment)
        if not query:
            return []
        end = int(time.time())
        start = end - int(since_hours) * 3600
        data = self._get_json(
            "/api/search",
            {
                "q": str(query),
                "start": str(start),
                "end": str(end),
                "limit": int(self.config.get("limit", 20)),
            },
        )
        floor = float(self.config.get("min_duration_ms", 0) or 0)
        traces = [
            self._normalize(raw) for raw in data.get("traces", [])
        ]
        traces = [trace for trace in traces if trace["duration_ms"] >= floor]
        # Slowest first: the interesting trace is the one that took long.
        traces.sort(key=lambda trace: trace["duration_ms"], reverse=True)
        return traces

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
        """Provider payload -> the shape the rest of Baygon knows."""
        return {
            "id": str(raw.get("traceID", "")),
            "service": str(raw.get("rootServiceName", "")),
            "name": str(raw.get("rootTraceName", "")),
            "duration_ms": float(raw.get("durationMs", 0) or 0),
            "start": str(raw.get("startTimeUnixNano", "")),
        }
