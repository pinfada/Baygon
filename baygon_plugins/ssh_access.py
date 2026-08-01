"""SSH capability returning declared connection commands.

Baygon gives access to authorized remote resources (EF-010) without
replacing the tools: it returns the ssh command declared in
configuration and the user's terminal runs it. Targets map environments
to `user@host` in the provider options.

    providers:
      remote:
        type: ssh
        plugin: baygon_plugins.ssh_access:SSHAccess
        options:
          targets:
            staging: deploy@staging.example.com
            production: deploy@prod.example.com
          options: "-p 2222"        # optional extra ssh arguments
"""

from __future__ import annotations

from typing import Any

from baygon.capabilities import SSHCapability


class SSHAccess(SSHCapability):
    identifier = "ssh-access"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def command(self, environment: str, **params: Any) -> dict[str, Any]:
        targets = self.config.get("targets") or {}
        target = targets.get(environment)
        if not target:
            raise ValueError(
                f"no ssh target declared for environment {environment!r}; "
                "declare it under options.targets in baygon.yaml"
            )
        extra = str(self.config.get("options", "")).strip()
        parts = ["ssh"] + ([extra] if extra else []) + [str(target)]
        return {"environment": environment, "command": " ".join(parts)}
