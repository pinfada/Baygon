"""Deployment capability backed by the Render REST API.

Real cloud adapter: Baygon never deploys directly (EF-008), it asks
Render to do it. Environments map to Render service ids in the provider
options; the API key comes from the environment (EF-011). Swapping
Render for Fly.io or another cloud only requires a new adapter and a
baygon.yaml change.

    providers:
      cloud:
        type: deployment
        plugin: baygon_plugins.render_deploy:RenderDeployment
        options:
          services:
            staging: srv-xxxxx
            production: srv-yyyyy
          api_key_env: RENDER_API_KEY   # optional
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from baygon.capabilities import DeploymentCapability

API_BASE = "https://api.render.com/v1"


class RenderDeployment(DeploymentCapability):
    identifier = "render"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "baygon"}
        key = os.environ.get(str(self.config.get("api_key_env", "RENDER_API_KEY")))
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            API_BASE + path, data=data, method=method, headers=self._headers()
        )
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def _service(self, environment: str) -> str:
        services = self.config.get("services", {})
        service = services.get(environment)
        if not service:
            raise ValueError(
                f"no Render service mapped for environment {environment!r}; "
                "declare it under options.services in baygon.yaml"
            )
        return str(service)

    def health_check(self) -> bool:
        if "Authorization" not in self._headers():
            return False
        services = self.config.get("services", {})
        if services:
            first = next(iter(services.values()))
            self._request("GET", f"/services/{first}")
        return True

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        service = self._service(environment)
        deploy = self._request("POST", f"/services/{service}/deploys", body={})
        return {"environment": environment, "service": service, "deploy": deploy}

    def status(self, environment: str, **params: Any) -> dict[str, Any]:
        service = self._service(environment)
        deploys = self._request("GET", f"/services/{service}/deploys?limit=1")
        if not deploys:
            return {"environment": environment, "state": "unknown"}
        latest = deploys[0].get("deploy", deploys[0])
        return {
            "environment": environment,
            "state": latest.get("status", "unknown"),
            "commit": (latest.get("commit") or {}).get("id"),
        }

    def rollback(self, environment: str, **params: Any) -> dict[str, Any]:
        service = self._service(environment)
        deploys = self._request("GET", f"/services/{service}/deploys?limit=2")
        if len(deploys) < 2:
            return {"environment": environment, "state": "nothing-to-rollback"}
        previous = deploys[1].get("deploy", deploys[1])
        result = self._request(
            "POST", f"/services/{service}/rollback", body={"deployId": previous.get("id")}
        )
        return {"environment": environment, "state": "rolled-back", "deploy": result}
