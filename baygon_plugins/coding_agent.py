"""Developer capability backed by a coding-agent CLI.

Baygon never edits code itself: it orchestrates a specialized coding
agent (Claude Code by default — any agent CLI works) exactly like it
orchestrates git or flyctl. The agent modifies the sources in the
working directory; Baygon's declared `test` command then validates the
result independently, and failed QA reports are fed back through the
`feedback` argument (FixBug bounded loop).

    providers:
      dev:
        type: developer
        plugin: baygon_plugins.coding_agent:CodingAgent
        options:
          command: ["claude", "-p", "{prompt}"]   # default
          cwd: .
          timeout_seconds: 1800

Authentication is the agent's own (e.g. ANTHROPIC_API_KEY for Claude
Code) — never stored in baygon.yaml.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from baygon.capabilities import DeveloperCapability

DEFAULT_COMMAND = ["claude", "-p", "{prompt}"]


class CodingAgent(DeveloperCapability):
    identifier = "coding-agent"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Command seam — single overridable entry point, faked in tests.
    # ------------------------------------------------------------------

    def _run(self, args: list[str]) -> str:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(self.config.get("cwd", ".")),
            timeout=int(self.config.get("timeout_seconds", 1800)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"coding agent failed (exit {completed.returncode}): "
                f"{completed.stderr.strip()[:500]}"
            )
        return completed.stdout

    # ------------------------------------------------------------------

    def _command(self) -> list[str]:
        return [str(part) for part in self.config.get("command", DEFAULT_COMMAND)]

    def health_check(self) -> bool:
        command = self._command()
        return bool(command) and shutil.which(command[0]) is not None

    def fix(self, description: str, feedback: str | None = None, **params: Any) -> dict[str, Any]:
        prompt = description
        if feedback:
            prompt += (
                "\n\nA previous attempt did not pass the test suite. QA report:\n"
                + feedback
                + "\nFix the remaining problems."
            )
        args = [part.replace("{prompt}", prompt) for part in self._command()]
        output = self._run(args)
        return {"state": "patched", "output": output[-2000:]}
