"""Deployment capability backed by Fly.io (through flyctl).

Chapter 8's literal example — "Si demain Render est remplacé par
Fly.io : aucun changement dans Baygon" — made real: this adapter is the
second implementation of the `deployment` contract, and switching from
Render only touches baygon.yaml. Baygon orchestrates the specialized
flyctl CLI; it never deploys itself (EF-008). Authentication is
flyctl's own (FLY_API_TOKEN or `flyctl auth`), never Baygon's.

    providers:
      cloud:
        type: deployment
        plugin: baygon_plugins.fly_deploy:FlyDeployment
        options:
          apps:
            staging: myapp-stg
            production: myapp-prod
          timeout_seconds: 600
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from baygon.capabilities import DeploymentCapability


class FlyDeployment(DeploymentCapability):
    identifier = "fly"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Command seam — single overridable entry point, faked in tests.
    # ------------------------------------------------------------------

    def _flyctl(self, args: list[str]) -> str:
        completed = subprocess.run(
            ["flyctl", *args],
            capture_output=True,
            text=True,
            timeout=int(self.config.get("timeout_seconds", 600)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"flyctl {' '.join(args)} failed: {completed.stderr.strip()[:500]}"
            )
        return completed.stdout

    # ------------------------------------------------------------------

    def _app(self, environment: str) -> str:
        apps = self.config.get("apps") or {}
        app = apps.get(environment)
        if not app:
            raise ValueError(
                f"no Fly.io app mapped for environment {environment!r}; "
                "declare it under options.apps in baygon.yaml"
            )
        return str(app)

    def health_check(self) -> bool:
        return bool(self.config.get("apps")) and shutil.which("flyctl") is not None

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        app = self._app(environment)
        output = self._flyctl(["deploy", "--app", app, "--remote-only"])
        return {"environment": environment, "app": app, "state": "deployed",
                "output": output[-2000:]}

    def status(self, environment: str, **params: Any) -> dict[str, Any]:
        app = self._app(environment)
        raw = self._flyctl(["status", "--app", app, "--json"])
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        return {
            "environment": environment,
            "app": app,
            "state": str(parsed.get("Status", "unknown")).lower(),
        }

    def rollback(self, environment: str, **params: Any) -> dict[str, Any]:
        app = self._app(environment)
        output = self._flyctl(["releases", "rollback", "--app", app, "--yes"])
        return {"environment": environment, "app": app, "state": "rolled-back",
                "output": output[-2000:]}
