"""TDD — API hardening (ENF-005, ENF-009, ENF-011).

Security stays the default: the API throttles abusive clients (429 with
Retry-After, liveness exempt), ships security headers on every
response, and every authentication failure is published on the event
bus so it can be audited.
"""

import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell.api import make_server
from tests.helpers import MINIMAL_YAML


class HardenedApiTest(unittest.TestCase):
    def _start(self, rate_limit: int | None = None) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(MINIMAL_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        self.server = make_server(
            self.kernel, host="127.0.0.1", port=0, token="tok",
            rate_limit_per_minute=rate_limit,
        )
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _get(self, path: str, token: str | None = "tok"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read()
        return response, body

    def test_burst_beyond_the_limit_is_throttled(self) -> None:
        self._start(rate_limit=5)
        for _ in range(5):
            response, _ = self._get("/capabilities")
            self.assertEqual(response.status, 200)
        response, _ = self._get("/capabilities")
        self.assertEqual(response.status, 429)
        self.assertIsNotNone(response.getheader("Retry-After"))

    def test_liveness_is_exempt_from_throttling(self) -> None:
        self._start(rate_limit=2)
        for _ in range(2):
            self._get("/capabilities")
        for _ in range(4):
            response, _ = self._get("/health", token=None)
            self.assertEqual(response.status, 200)

    def test_no_rate_limit_by_default_in_make_server(self) -> None:
        self._start(rate_limit=None)
        for _ in range(10):
            response, _ = self._get("/capabilities")
            self.assertEqual(response.status, 200)

    def test_security_headers_on_json_responses(self) -> None:
        self._start()
        response, _ = self._get("/capabilities")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_security_headers_on_the_web_page(self) -> None:
        self._start()
        response, _ = self._get("/", token=None)
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("X-Frame-Options"), "DENY")

    def test_auth_failures_are_published_for_audit(self) -> None:
        self._start()
        seen: list = []
        self.kernel.bus.subscribe("AuthFailed", seen.append)
        self._get("/capabilities", token="wrong")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].payload["path"], "/capabilities")
        self.assertIn("client", seen[0].payload)


if __name__ == "__main__":
    unittest.main()
