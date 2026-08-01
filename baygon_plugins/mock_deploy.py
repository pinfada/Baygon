"""Deployment capability simulator.

Stands in for a real cloud provider adapter (Render, Fly.io, ...). It
demonstrates the contract; swapping it for a real adapter requires only
a change in ``baygon.yaml``.
"""

from __future__ import annotations

import datetime
from typing import Any

from baygon.capabilities import DeploymentCapability


class MockDeployment(DeploymentCapability):
    identifier = "mock-deploy"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._deployments: dict[str, dict[str, Any]] = {}

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        context = params.get("context") or {}
        commit = None
        for value in context.values():
            if isinstance(value, dict) and "sha" in value:
                commit = value["sha"]
        deployment = {
            "environment": environment,
            "commit": commit,
            "state": "live",
            "deployed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._deployments[environment] = deployment
        return deployment

    def status(self, environment: str, **params: Any) -> dict[str, Any]:
        return self._deployments.get(environment, {"environment": environment, "state": "unknown"})

    def rollback(self, environment: str, **params: Any) -> dict[str, Any]:
        deployment = self._deployments.pop(environment, None)
        return {
            "environment": environment,
            "state": "rolled-back" if deployment else "nothing-to-rollback",
        }
