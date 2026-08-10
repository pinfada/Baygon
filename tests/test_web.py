"""TDD — minimal web interface (EF-004, mobility principle).

The Shell gets its third face: a single mobile-friendly page served by
the API server. The page itself carries no project data and no business
logic — it only calls the same authenticated endpoints, so it is served
openly like /health, while every data call still requires the token.
"""

import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell import web
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

    def test_the_page_is_never_cached(self) -> None:
        """The page ships with the server, so it must not outlive it.

        A cached copy is an older Baygon's interface driving a newer
        one — including one whose bug the upgrade just fixed.
        """
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        response = conn.getresponse()
        response.read()
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_page_contains_no_project_data(self) -> None:
        _, _, body = self._get("/")
        self.assertNotIn("demo", body)  # the project name never leaks

    def test_data_endpoints_still_require_the_token(self) -> None:
        status, _, _ = self._get("/capabilities")
        self.assertEqual(status, 401)

    def test_the_browser_receives_every_escape_the_source_wrote(self) -> None:
        """A page that is served is not a page that works.

        The page carries JavaScript, so a backslash written in this
        repository is meant for the browser. If `PAGE` stops being a raw
        string, Python consumes those escapes: `\\'` arrives as a bare
        quote, the string ends early, the parser gives up and every
        button on the page goes dead — while every substring assertion
        here still passes, and the server still answers 200.

        Counting is enough, and needs no JavaScript parser: an escape
        eaten by Python is an escape missing from what is served.
        """
        source = Path(web.__file__).read_text(encoding="utf-8")
        # Slice at the assignment so the comment above it does not count.
        literal = source.split("PAGE = ", 1)[1]
        self.assertEqual(
            web.PAGE.count("\\"), literal.count("\\"),
            "escapes were lost between the source and the served page: "
            "PAGE must stay a raw string (r\"\"\"...\"\"\")",
        )

    def test_every_handler_the_page_wires_up_is_defined(self) -> None:
        """An onclick naming a function that does not exist is a dead button."""
        _, _, body = self._get("/")
        script = script_of(body)
        defined = set(re.findall(r"(?:function\s+|const\s+|let\s+)(\w+)\s*[(=]", script))
        called = set(re.findall(r"on\w+=\"(\w+)\(", body))
        self.assertTrue(called, "the page wires no handler at all")
        self.assertEqual(called - defined, set())


def script_of(html: str) -> str:
    """The page's inline script, or "" when there is none."""
    match = re.search(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    return match.group(1) if match else ""


if __name__ == "__main__":
    unittest.main()
