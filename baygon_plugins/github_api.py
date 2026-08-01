"""Repository capability backed by the GitHub REST API.

First real provider adapter. Declared in baygon.yaml like any plugin:

    providers:
      git:
        type: repository
        plugin: baygon_plugins.github_api:GitHubRepository
        options:
          repository: owner/repo
          token_env: GITHUB_TOKEN   # optional, name of the env variable

The token is read from the environment (or put there by the secrets
manager) — never from the configuration file (EF-011). Swapping GitHub
for GitLab, Forgejo or a local clone only requires another adapter.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import RepositoryCapability

API_BASE = "https://api.github.com"


class GitHubRepository(RepositoryCapability):
    identifier = "github"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "baygon",
        }
        token = os.environ.get(self.config.get("token_env", "GITHUB_TOKEN"))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_json(self, path: str) -> Any:
        request = urllib.request.Request(API_BASE + path, headers=self._headers())
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def _repo(self) -> str:
        repository = self.config.get("repository")
        if not repository or "/" not in str(repository):
            raise ValueError("option 'repository' (owner/repo) is required")
        return urllib.parse.quote(str(repository))

    def health_check(self) -> bool:
        self._get_json(f"/repos/{self._repo()}")
        return True

    @staticmethod
    def _map_commit(payload: dict[str, Any]) -> dict[str, Any]:
        commit = payload.get("commit", {})
        return {
            "sha": payload.get("sha", ""),
            "author": commit.get("author", {}).get("name", ""),
            "subject": str(commit.get("message", "")).splitlines()[0] if commit.get("message") else "",
        }

    def get_latest_commit(self, **params: Any) -> dict[str, Any]:
        commits = self._get_json(f"/repos/{self._repo()}/commits?per_page=1")
        if not commits:
            raise RuntimeError("repository has no commits")
        return self._map_commit(commits[0])

    def history(self, limit: int = 10, **params: Any) -> list[dict[str, Any]]:
        commits = self._get_json(f"/repos/{self._repo()}/commits?per_page={int(limit)}")
        return [self._map_commit(entry) for entry in commits[: int(limit)]]

    def diff(self, **params: Any) -> str:
        commits = self._get_json(f"/repos/{self._repo()}/commits?per_page=1")
        if not commits:
            return ""
        detail = self._get_json(f"/repos/{self._repo()}/commits/{commits[0]['sha']}")
        lines = [
            f"{item.get('filename')} +{item.get('additions', 0)} -{item.get('deletions', 0)}"
            for item in detail.get("files", [])
        ]
        return "\n".join(lines)
