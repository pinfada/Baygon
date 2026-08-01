"""TDD — minimal web interface (EF-004, mobility principle).

The Shell gets its third face: a single mobile-friendly page served by
the API server. The page itself carries no project data and no business
logic — it only calls the same authenticated endpoints, so it is served
openly like /health, while every data call still requires the token.
"""

import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell.api import make_server
from tests.helpers import MINIMAL_YAML


class WebUiTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(MINIMAL_YAML, encoding="utf-8")
        kernel = Kernel.start(tmp.name)
        self.server = make_server(kernel, host="127.0.0.1", port=0, token="tok")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type", ""), response.read().decode("utf-8")

    def test_root_serves_the_web_shell_without_auth(self) -> None:
        status, content_type, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("Baygon", body)
        # The page drives the same API: it references the run endpoint
        # and the Authorization header, and asks for the token.
        self.assertIn("/run", body)
        self.assertIn("Authorization", body)

    def test_page_is_mobile_friendly(self) -> None:
        _, _, body = self._get("/")
        self.assertIn("viewport", body)

    def test_page_contains_no_project_data(self) -> None:
        _, _, body = self._get("/")
        self.assertNotIn("demo", body)  # the project name never leaks

    def test_data_endpoints_still_require_the_token(self) -> None:
        status, _, _ = self._get("/capabilities")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
