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

import os
import shutil
import subprocess
from typing import Any

from baygon.capabilities import ActionableError, DeveloperCapability
from baygon_plugins._process import failure_message


class CodingAgent(DeveloperCapability):
    identifier = "coding-agent"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Command seam — single overridable entry point, faked in tests.
    # ------------------------------------------------------------------

    def _run(self, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.resolve_path(self.config.get("cwd"))),
                timeout=int(self.config.get("timeout_seconds", 1800)),
            )
        except OSError as exc:
            # Typically a program the system cannot launch directly —
            # a script without an interpreter on Windows. Say which
            # command failed and how to declare it portably, rather
            # than let a bare "cannot find the file" surface.
            raise RuntimeError(
                f"cannot launch the coding agent {args[0]!r}: {exc}. "
                "When the program is not directly executable on this system, "
                "declare its interpreter: [\"python\", \"agent.py\"]."
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(failure_message("coding agent", completed))
        return completed.stdout

    # ------------------------------------------------------------------

    def _command(self) -> list[str]:
        command = self.config.get("command")
        if not command:
            # No vendor default (ENF-019): the agent must be declared.
            raise ActionableError(
                "no coding agent declared: option 'command' is required",
                [
                    'declare options.command in baygon.yaml, e.g. ["claude", "-p", "{prompt}"]',
                    'or ["aider", "--message", "{prompt}", "--yes"], or any other agent CLI',
                ],
            )
        return [str(part) for part in command]

    def _extension_decides_what_is_executable(self) -> bool:
        """True where the system has no executable bit.

        Windows judges a program by its extension: `shutil.which` there
        accepts only what PATHEXT lists, a rule Python enforces since
        3.12. Elsewhere the executable bit settles the question.

        Platform seam — single overridable entry point, faked in tests.
        """
        return os.name == "nt"

    def health_check(self) -> bool:
        command = self.config.get("command")
        if not command:
            return False
        program = str(command[0])
        # A program looked up on PATH is only usable if it is found
        # there; claiming otherwise would be a guess.
        if not program.startswith("."):
            return shutil.which(program) is not None
        # A relative program (e.g. ./agent.sh) belongs to the project.
        resolved = self.resolve_path(program)
        if shutil.which(str(resolved)) is not None:
            return True
        # Where extensions decide, a project that ships `./agent.py` and
        # declares it would see its agent reported missing although the
        # file is right there. A program the project ships *and*
        # declares is taken at its word; if it truly cannot be launched,
        # `fix()` says so and names the command.
        return self._extension_decides_what_is_executable() and resolved.is_file()

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
