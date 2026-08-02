"""Service capability driving declared supervisor commands.

Baygon does not manage processes: it runs the command you declared for
each service, whatever the supervisor is (systemd, Docker, kubectl, a
cloud CLI...).

    providers:
      services:
        type: service
        plugin: baygon_plugins.command_service:CommandService
        options:
          services:
            worker: "systemctl restart myapp-worker"
            api: "docker compose restart api"
          cwd: .
          timeout_seconds: 120
"""

from __future__ import annotations

import subprocess
from typing import Any

from baygon.capabilities import ServiceCapability


class CommandService(ServiceCapability):
    identifier = "command-service"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # Single overridable seam, faked in tests.
    def _run(self, command_line: str) -> str:
        completed = subprocess.run(
            command_line,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(self.config.get("cwd", ".")),
            timeout=int(self.config.get("timeout_seconds", 120)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"restart failed (exit {completed.returncode}): "
                f"{completed.stderr.strip()[:500]}"
            )
        return completed.stdout

    def health_check(self) -> bool:
        return bool(self.config.get("services"))

    def restart(self, service: str, environment: str, **params: Any) -> dict[str, Any]:
        services = self.config.get("services") or {}
        command_line = services.get(service)
        if not command_line:
            known = ", ".join(sorted(services)) or "none"
            raise ValueError(
                f"no command declared for service {service!r}; "
                f"declared services: {known} (options.services in baygon.yaml)"
            )
        output = self._run(str(command_line))
        return {
            "service": service,
            "environment": environment,
            "state": "restarted",
            "output": output[-2000:],
        }
