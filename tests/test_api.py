import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell.api import make_server
from tests.helpers import MINIMAL_YAML

API_YAML = MINIMAL_YAML.replace(
    "providers: {}",
    "providers:\n"
    "  cloud:\n"
    "    type: deployment\n"
    "    plugin: tests.helpers:FakeDeployment\n"
    "    default: true\n"
    "  git:\n"
    "    type: repository\n"
    "    plugin: tests.helpers:FakeRepository\n"
    "    default: true",
)


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(API_YAML, encoding="utf-8")
        kernel = Kernel.start(tmp.name)
        self.server = make_server(kernel, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _request(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_health(self) -> None:
        status, data = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ready"])
        self.assertEqual(data["project"], "demo")

    def test_capabilities_and_context(self) -> None:
        status, data = self._request("GET", "/capabilities")
        self.assertEqual(status, 200)
        self.assertIn("deployment", data)
        status, data = self._request("GET", "/context")
        self.assertEqual(status, 200)
        self.assertEqual(data["project"]["name"], "demo")

    def test_plan_endpoint_explains(self) -> None:
        status, data = self._request("POST", "/plan", {"intent": "deploy to staging"})
        self.assertEqual(status, 200)
        self.assertEqual(data["plan"]["intent"]["name"], "DeployProject")
        self.assertIn("Reasoning", data["explanation"])

    def test_run_executes_and_records_history(self) -> None:
        status, data = self._request("POST", "/run", {"intent": "deploy to staging"})
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        status, entries = self._request("GET", "/history")
        self.assertEqual(status, 200)
        self.assertEqual(entries[-1]["intent"], "DeployProject")
        self.assertEqual(entries[-1]["plan"]["intent"]["source"], "api")

    def test_sensitive_run_requires_approval(self) -> None:
        status, data = self._request("POST", "/run", {"intent": "deploy to production"})
        self.assertEqual(status, 428)
        self.assertIn("approved", data["hint"])
        status, data = self._request(
            "POST", "/run", {"intent": "deploy to production", "approved": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])

    def test_unknown_intent_is_400(self) -> None:
        status, data = self._request("POST", "/run", {"intent": "fais-moi un café"})
        self.assertEqual(status, 400)
        self.assertIn("DeployProject", data["supported"])

    def test_bad_body_is_400_and_unknown_path_404(self) -> None:
        status, _ = self._request("POST", "/run", None)
        self.assertEqual(status, 400)
        status, _ = self._request("GET", "/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
