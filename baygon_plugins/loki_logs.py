"""Logs capability backed by Grafana Loki.

Baygon consults logs where they already live and stores nothing
(EF-007). Each environment maps to a LogQL query in the provider
options; an optional bearer token comes from the environment.

    providers:
      logging:
        type: logs
        plugin: baygon_plugins.loki_logs:LokiLogs
        options:
          url: https://loki.example.com
          queries:
            production: '{app="myapp", env="prod"}'
            staging: '{app="myapp", env="stg"}'
          max_lines: 200
          token_env: LOKI_TOKEN   # optional
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import LogsCapability


class LokiLogs(LogsCapability):
    identifier = "loki"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "baygon"}
        token = os.environ.get(str(self.config.get("token_env", "LOKI_TOKEN")))
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

    def fetch(self, environment: str, since_hours: int = 1, **params: Any) -> list[str]:
        query = (self.config.get("queries") or {}).get(environment)
        if not query:
            return []
        end_ns = int(time.time() * 1_000_000_000)
        start_ns = end_ns - int(since_hours) * 3600 * 1_000_000_000
        data = self._get_json(
            "/loki/api/v1/query_range",
            {
                "query": str(query),
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": int(self.config.get("max_lines", 100)),
            },
        )
        entries: list[tuple[int, str]] = []
        for stream in data.get("data", {}).get("result", []):
            for timestamp, line in stream.get("values", []):
                entries.append((int(timestamp), str(line)))
        return [line for _, line in sorted(entries)]
