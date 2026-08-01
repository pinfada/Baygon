"""TDD — GitHub adapter for the Repository capability.

First real provider adapter. The core is never touched: the adapter is
declared in baygon.yaml like any other plugin. The API token is read
from the environment (never stored in clear text). The HTTP transport
is a single overridable method, faked in these tests.
"""

import os
import unittest
from typing import Any

from baygon_plugins.github_api import GitHubRepository

COMMITS = [
    {
        "sha": "abc123",
        "commit": {"author": {"name": "alice"}, "message": "Fix login\n\ndetails"},
    },
    {
        "sha": "def456",
        "commit": {"author": {"name": "bob"}, "message": "Add feature"},
    },
]


class FakeGitHub(GitHubRepository):
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


class GitHubRepositoryTest(unittest.TestCase):
    def _adapter(self) -> FakeGitHub:
        adapter = FakeGitHub({"repository": "pinfada/Baygon"})
        adapter.payloads["/repos/pinfada/Baygon/commits"] = COMMITS
        adapter.payloads["/repos/pinfada/Baygon"] = {"full_name": "pinfada/Baygon"}
        return adapter

    def test_get_latest_commit_maps_github_payload(self) -> None:
        commit = self._adapter().get_latest_commit()
        self.assertEqual(commit["sha"], "abc123")
        self.assertEqual(commit["author"], "alice")
        # Only the first line of the message becomes the subject.
        self.assertEqual(commit["subject"], "Fix login")

    def test_history_maps_and_limits(self) -> None:
        adapter = self._adapter()
        history = adapter.history(limit=2)
        self.assertEqual([c["sha"] for c in history], ["abc123", "def456"])
        self.assertTrue(any("per_page=2" in path for path in adapter.requested))

    def test_requests_target_the_configured_repository(self) -> None:
        adapter = self._adapter()
        adapter.get_latest_commit()
        self.assertTrue(all("/repos/pinfada/Baygon" in p for p in adapter.requested))

    def test_health_check_queries_the_repository(self) -> None:
        adapter = self._adapter()
        self.assertTrue(adapter.health_check())
        self.assertIn("/repos/pinfada/Baygon", adapter.requested)

    def test_missing_repository_option_fails_health_check(self) -> None:
        adapter = FakeGitHub({})
        with self.assertRaises(Exception):
            adapter.health_check()

    def test_token_read_from_environment_never_from_config(self) -> None:
        os.environ["GHTEST_TOKEN"] = "tok-123"
        self.addCleanup(os.environ.pop, "GHTEST_TOKEN", None)
        adapter = FakeGitHub({"repository": "a/b", "token_env": "GHTEST_TOKEN"})
        headers = adapter._headers()
        self.assertEqual(headers["Authorization"], "Bearer tok-123")

    def test_no_token_means_no_authorization_header(self) -> None:
        adapter = FakeGitHub({"repository": "a/b", "token_env": "GHTEST_ABSENT"})
        self.assertNotIn("Authorization", adapter._headers())


if __name__ == "__main__":
    unittest.main()
