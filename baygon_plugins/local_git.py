"""Repository capability backed by a local git working copy.

Baygon never replaces git: this adapter only shells out to the git CLI.
"""

from __future__ import annotations

import subprocess
from typing import Any

from baygon.capabilities import RepositoryCapability


class LocalGitRepository(RepositoryCapability):
    identifier = "local-git"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def _git(self, *args: str) -> str:
        path = self.resolve_path(self.config.get("path"))
        completed = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True, text=True, timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    def health_check(self) -> bool:
        self._git("rev-parse", "--is-inside-work-tree")
        return True

    def get_latest_commit(self, **params: Any) -> dict[str, Any]:
        line = self._git("log", "-1", "--format=%H|%an|%s")
        sha, author, subject = line.split("|", 2)
        return {"sha": sha, "author": author, "subject": subject}

    def history(self, limit: int = 10, **params: Any) -> list[dict[str, Any]]:
        lines = self._git("log", f"-{limit}", "--format=%H|%an|%s").splitlines()
        return [
            dict(zip(("sha", "author", "subject"), line.split("|", 2)))
            for line in lines if line
        ]

    def diff(self, **params: Any) -> str:
        return self._git("diff", "--stat")
