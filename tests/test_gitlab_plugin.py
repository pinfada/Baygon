"""TDD — GitLab adapter for the Repository capability.

Second real implementation of the `repository` contract (next to
GitHub): swapping Git providers is a baygon.yaml change, never a core
change (Article 4). Token from the environment; injectable transport.
"""

import os
import unittest
from typing import Any

from baygon_plugins.gitlab_api import GitLabRepository

COMMITS = [
    {"id": "abc123", "author_name": "alice", "title": "Fix login"},
    {"id": "def456", "author_name": "bob", "title": "Add feature"},
]


class FakeGitLab(GitLabRepository):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requested: list[str] = []
        self.payloads: dict[str, Any] = {}

    def _get_json(self, path: str) -> Any:
        self.requested.append(path)
        for prefix, payload in self.payloads.items():
            if path.startswith(prefix):
                return payload
        raise RuntimeError(f"unexpected path {path}")


def _adapter() -> FakeGitLab:
    adapter = FakeGitLab({"project": "group/app"})
    adapter.payloads["/projects/group%2Fapp/repository/commits"] = COMMITS
    adapter.payloads["/projects/group%2Fapp"] = {"path_with_namespace": "group/app"}
    return adapter


class GitLabRepositoryTest(unittest.TestCase):
    def test_get_latest_commit_maps_gitlab_payload(self) -> None:
        commit = _adapter().get_latest_commit()
        self.assertEqual(
            commit, {"sha": "abc123", "author": "alice", "subject": "Fix login"}
        )

    def test_project_path_is_url_encoded(self) -> None:
        adapter = _adapter()
        adapter.get_latest_commit()
        self.assertIn("/projects/group%2Fapp/repository/commits", adapter.requested[0])

    def test_history_maps_and_limits(self) -> None:
        adapter = _adapter()
        history = adapter.history(limit=2)
        self.assertEqual([c["sha"] for c in history], ["abc123", "def456"])
        self.assertTrue(any("per_page=2" in path for path in adapter.requested))

    def test_token_header_is_private_token_from_environment(self) -> None:
        os.environ["GLTEST_TOKEN"] = "glpat-123"
        self.addCleanup(os.environ.pop, "GLTEST_TOKEN", None)
        adapter = FakeGitLab({"project": "a/b", "token_env": "GLTEST_TOKEN"})
        self.assertEqual(adapter._headers()["PRIVATE-TOKEN"], "glpat-123")

    def test_missing_project_option_fails_health_check(self) -> None:
        adapter = FakeGitLab({})
        with self.assertRaises(Exception):
            adapter.health_check()


if __name__ == "__main__":
    unittest.main()
