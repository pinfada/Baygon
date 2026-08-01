"""TDD — Render adapter for the Deployment capability.

Real cloud provider adapter. Environments map to Render service ids in
the provider options; the API key comes from the environment (EF-011).
The HTTP transport is a single overridable seam, faked here.
"""

import os
import unittest
from typing import Any

from baygon_plugins.render_deploy import RenderDeployment


class FakeRender(RenderDeployment):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.payloads: dict[str, Any] = {}

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.requests.append((method, path, body))
        for prefix, payload in self.payloads.items():
            if path.startswith(prefix):
                return payload
        raise RuntimeError(f"unexpected path {path}")


def _adapter() -> FakeRender:
    adapter = FakeRender({"services": {"staging": "srv-stg", "production": "srv-prod"}})
    adapter.payloads["/services/srv-stg/deploys"] = [
        {"deploy": {"id": "dep-1", "status": "live", "commit": {"id": "abc123"}}}
    ]
    adapter.payloads["/services/srv-stg"] = {"service": {"id": "srv-stg"}}
    return adapter


class RenderDeploymentTest(unittest.TestCase):
    def test_deploy_posts_to_the_mapped_service(self) -> None:
        adapter = _adapter()
        result = adapter.deploy("staging")
        method, path, _ = adapter.requests[0]
        self.assertEqual((method, path), ("POST", "/services/srv-stg/deploys"))
        self.assertEqual(result["environment"], "staging")

    def test_status_reads_latest_deploy(self) -> None:
        adapter = _adapter()
        status = adapter.status("staging")
        method, path, _ = adapter.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("/services/srv-stg/deploys", path)
        self.assertEqual(status["state"], "live")
        self.assertEqual(status["commit"], "abc123")

    def test_unmapped_environment_raises(self) -> None:
        adapter = _adapter()
        with self.assertRaisesRegex(ValueError, "development"):
            adapter.deploy("development")

    def test_api_key_read_from_environment_never_from_config(self) -> None:
        os.environ["RENDER_TEST_KEY"] = "rnd-123"
        self.addCleanup(os.environ.pop, "RENDER_TEST_KEY", None)
        adapter = FakeRender({"services": {}, "api_key_env": "RENDER_TEST_KEY"})
        self.assertEqual(adapter._headers()["Authorization"], "Bearer rnd-123")

    def test_health_check_fails_without_api_key(self) -> None:
        os.environ.pop("RENDER_TEST_ABSENT", None)
        adapter = FakeRender({"services": {"staging": "srv-stg"}, "api_key_env": "RENDER_TEST_ABSENT"})
        self.assertFalse(adapter.health_check())


if __name__ == "__main__":
    unittest.main()
