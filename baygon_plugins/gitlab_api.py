"""Repository capability backed by the GitLab REST API.

Second real Git provider (next to GitHub): swapping providers is a
baygon.yaml change, never a core change (Article 4). Works with
gitlab.com and self-hosted instances.

    providers:
      git:
        type: repository
        plugin: baygon_plugins.gitlab_api:GitLabRepository
        options:
          project: group/app
          endpoint: https://gitlab.com   # optional, self-hosted instances
          token_env: GITLAB_TOKEN        # optional

The token is read from the environment (EF-011), never from
configuration.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import RepositoryCapability


class GitLabRepository(RepositoryCapability):
    identifier = "gitlab"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "baygon"}
        token = os.environ.get(str(self.config.get("token_env", "GITLAB_TOKEN")))
        if token:
            headers["PRIVATE-TOKEN"] = token
        return headers

    def _get_json(self, path: str) -> Any:
        base = str(self.config.get("endpoint", "https://gitlab.com")).rstrip("/")
        request = urllib.request.Request(base + "/api/v4" + path, headers=self._headers())
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def _project(self) -> str:
        project = self.config.get("project")
        if not project or "/" not in str(project):
            raise ValueError("option 'project' (group/name) is required")
        return urllib.parse.quote(str(project), safe="")

    def health_check(self) -> bool:
        self._get_json(f"/projects/{self._project()}")
        return True

    @staticmethod
    def _map_commit(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "sha": payload.get("id", ""),
            "author": payload.get("author_name", ""),
            "subject": payload.get("title", ""),
        }

    def get_latest_commit(self, **params: Any) -> dict[str, Any]:
        commits = self._get_json(f"/projects/{self._project()}/repository/commits?per_page=1")
        if not commits:
            raise RuntimeError("repository has no commits")
        return self._map_commit(commits[0])

    def history(self, limit: int = 10, **params: Any) -> list[dict[str, Any]]:
        commits = self._get_json(
            f"/projects/{self._project()}/repository/commits?per_page={int(limit)}"
        )
        return [self._map_commit(entry) for entry in commits[: int(limit)]]

    def diff(self, **params: Any) -> str:
        commits = self._get_json(f"/projects/{self._project()}/repository/commits?per_page=1")
        if not commits:
            return ""
        sha = commits[0]["id"]
        entries = self._get_json(f"/projects/{self._project()}/repository/commits/{sha}/diff")
        return "\n".join(str(entry.get("new_path", "")) for entry in entries)
