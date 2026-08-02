"""Workspace capability executing declared commands in a local shell.

The command lines come exclusively from the `commands` section of
baygon.yaml — this adapter never decides what to run, only where.
"""

from __future__ import annotations

import subprocess
from typing import Any

from baygon.capabilities import WorkspaceCapability


class LocalShellWorkspace(WorkspaceCapability):
    identifier = "local-shell"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def execute(self, command: str, command_line: str, environment: str, **params: Any) -> dict[str, Any]:
        completed = subprocess.run(
            command_line,
            shell=True,
            capture_output=True,
            text=True,
            cwd=self.resolve_path(self.config.get("cwd")),
            timeout=int(self.config.get("timeout_seconds", 300)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"command {command!r} failed with exit code {completed.returncode}: "
                f"{completed.stderr.strip()[:500]}"
            )
        return {
            "command": command,
            "environment": environment,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-2000:],
        }
