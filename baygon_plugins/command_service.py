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

from baygon.capabilities import ActionableError, ServiceCapability
from baygon_plugins._process import failure_message


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
            cwd=str(self.resolve_path(self.config.get("cwd"))),
            timeout=int(self.config.get("timeout_seconds", 120)),
        )
        if completed.returncode != 0:
            raise RuntimeError(failure_message("restart", completed))
        return completed.stdout

    def health_check(self) -> bool:
        return bool(self.config.get("services"))

    def restart(self, service: str, environment: str, **params: Any) -> dict[str, Any]:
        services = self.config.get("services") or {}
        command_line = services.get(service)
        if not command_line:
            known = ", ".join(sorted(services)) or "none"
            # The list belongs in the message too: the cause is what
            # most views show first, and it must stand on its own.
            raise ActionableError(
                f"no command declared for service {service!r}; declared services: {known}",
                [
                    f"target one of: {known}",
                    f"or declare options.services.{service} in baygon.yaml",
                ],
            )
        output = self._run(str(command_line))
        # Acting is not observing. What comes back is what was seen, or
        # an honest admission that nothing was.
        observed = self._observe(service)
        return {
            "service": service,
            "environment": environment,
            "output": output[-2000:],
            **observed,
        }

    def status(self, service: str, environment: str, **params: Any) -> dict[str, Any]:
        commands = self.config.get("status") or {}
        if not commands.get(service):
            known = ", ".join(sorted(commands)) or "none"
            raise ActionableError(
                f"no status command declared for service {service!r}; "
                f"observable services: {known}",
                [
                    f"declare options.status.{service} in baygon.yaml, "
                    "e.g. 'docker compose ps --status running web'",
                    "Baygon does not inspect processes itself; it asks what you declared",
                ],
            )
        return {"service": service, "environment": environment, **self._observe(service)}

    def _observe(self, service: str) -> dict[str, Any]:
        """Run the declared status command, and say plainly what it told.

        Three honest outcomes: what was seen, nothing seen, or unknown
        — never "restarted" on the strength of an exit code alone.
        """
        command_line = (self.config.get("status") or {}).get(service)
        if not command_line:
            return {"state": "restart-requested", "verified": False,
                    "observation_error": "no status command declared for this service"}
        try:
            seen = self._run(str(command_line)).strip()
        except Exception as exc:
            return {"state": "unknown", "verified": False, "observation_error": str(exc)}
        return {
            "state": seen[-500:] if seen else "nothing-observed",
            "verified": True,
        }
