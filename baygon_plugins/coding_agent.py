"""Developer capability backed by any coding-agent CLI.

Baygon never edits code itself and favors no AI provider (ENF-019): it
orchestrates whichever coding agent the configuration declares, exactly
like it orchestrates git or flyctl. There is deliberately **no default
agent** — the command is required (chapter 6: ambiguous defaults are
forbidden). The agent modifies the sources in the working directory;
Baygon's declared `test` command then validates the result
independently, and failed QA reports are fed back through the
`feedback` argument (FixBug bounded loop).

Example command templates ({prompt} is substituted):

    command: ["claude", "-p", "{prompt}"]            # Claude Code
    command: ["aider", "--message", "{prompt}", "--yes"]
    command: ["codex", "exec", "{prompt}"]           # OpenAI Codex CLI
    command: ["gemini", "-p", "{prompt}"]            # Gemini CLI
    command: ["opencode", "run", "{prompt}"]

    providers:
      dev:
        type: developer
        plugin: baygon_plugins.coding_agent:CodingAgent
        options:
          command: ["<agent>", "...", "{prompt}"]   # required, your choice
          cwd: .
          timeout_seconds: 1800

Authentication is the agent's own (its API key environment variable) —
never stored in baygon.yaml. Swapping agents is a one-line
configuration change, and several developer implementations can
coexist in the registry (default / explicitly requested).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from baygon.capabilities import DeveloperCapability


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
        command = self.config.get("command")
        if not command:
            # No vendor default (ENF-019): the agent must be declared.
            raise ValueError(
                "option 'command' is required: declare your coding agent CLI in "
                "baygon.yaml (e.g. [\"claude\", \"-p\", \"{prompt}\"], "
                "[\"aider\", \"--message\", \"{prompt}\", \"--yes\"], ...)"
            )
        return [str(part) for part in command]

    def health_check(self) -> bool:
        command = self.config.get("command")
        return bool(command) and shutil.which(str(command[0])) is not None

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
