"""Review capability backed by GitHub: branch push + pull request.

Baygon does not write the diff — the coding agent already did. This
adapter commits whatever is in the working tree onto a dedicated
branch, pushes it, and asks GitHub to open a pull request. Nothing
leaves the machine without the plan being explicitly validated
(Article 9) and the `publish` permission being granted.

    providers:
      review:
        type: review
        plugin: baygon_plugins.github_review:GitHubReview
        options:
          repository: owner/repo
          base: main                 # optional, default "main"
          cwd: .                     # optional
          token_env: GITHUB_TOKEN    # optional
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from typing import Any

from baygon.capabilities import ReviewCapability

API_BASE = "https://api.github.com"


class GitHubReview(ReviewCapability):
    identifier = "github-review"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Seams — overridden in tests.
    # ------------------------------------------------------------------

    def _git(self, args: list[str]) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.resolve_path(self.config.get("cwd"))), *args],
            capture_output=True, text=True, timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()[:500]}")
        return completed.stdout

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "baygon",
        }
        token = os.environ.get(str(self.config.get("token_env", "GITHUB_TOKEN")))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            API_BASE + path, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def _repository(self) -> str:
        repository = self.config.get("repository")
        if not repository or "/" not in str(repository):
            raise ValueError("option 'repository' (owner/repo) is required")
        return str(repository)

    def health_check(self) -> bool:
        return bool(self.config.get("repository"))

    def publish(self, title: str, body: str = "", **params: Any) -> dict[str, Any]:
        if not self._git(["status", "--porcelain"]).strip():
            return {"state": "nothing-to-publish"}

        base = str(self.config.get("base", "main"))
        branch = f"baygon/{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}"
        self._git(["checkout", "-b", branch])
        self._git(["add", "-A"])
        self._git(["commit", "-m", title])
        self._git(["push", "-u", "origin", branch])

        pull = self._post_json(
            f"/repos/{self._repository()}/pulls",
            {"title": title, "body": body, "head": branch, "base": base},
        )
        return {
            "state": "published",
            "branch": branch,
            "url": str(pull.get("html_url", "")),
            "number": pull.get("number"),
        }
