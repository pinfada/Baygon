"""TDD — hot reload (chapter 10).

The Registry can add, remove or update implementations without
restarting Baygon: kernel.reload() re-reads baygon.yaml and rebuilds
the capability catalog in place. An invalid new file leaves the running
state untouched (an invalid file forbids execution, chapter 6), and the
audit history survives the reload.
"""

import http.client
import json
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

from baygon.core.errors import ConfigError
from baygon.core.kernel import Kernel
from baygon.shell.api import make_server

BASE_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      deploy: true
      production: true
    """
)

WITH_LOGS_YAML = BASE_YAML.replace(
    "  git:",
    "  logging:\n"
    "    type: logs\n"
    "    plugin: tests.helpers:FakeLogs\n"
    "    default: true\n"
    "  git:",
)

WITHOUT_DEPLOY_YAML = BASE_YAML.replace(
    "  cloud:\n"
    "    type: deployment\n"
    "    plugin: tests.helpers:FakeDeployment\n"
    "    default: true\n",
    "",
)


class HotReloadTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "baygon.yaml"
        self.file.write_text(BASE_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_reload_picks_up_a_new_provider(self) -> None:
        self.assertNotIn("logs", self.kernel.capabilities())
        self.file.write_text(WITH_LOGS_YAML, encoding="utf-8")
        self.kernel.reload()
        self.assertIn("logs", self.kernel.capabilities())
        result = self.kernel.run("show me the logs in staging")
        self.assertTrue(result.success)

    def test_reload_removes_a_withdrawn_provider(self) -> None:
        self.assertIn("deployment", self.kernel.capabilities())
        self.file.write_text(WITHOUT_DEPLOY_YAML, encoding="utf-8")
        self.kernel.reload()
        self.assertNotIn("deployment", self.kernel.capabilities())

    def test_invalid_new_file_leaves_running_state_untouched(self) -> None:
        self.file.write_text("nonsense: true", encoding="utf-8")
        with self.assertRaises(ConfigError):
            self.kernel.reload()
        # The previous configuration keeps working.
        self.assertIn("deployment", self.kernel.capabilities())
        self.assertTrue(self.kernel.run("deploy to staging").success)

    def test_history_survives_the_reload(self) -> None:
        self.kernel.run("deploy to staging")
        self.file.write_text(WITH_LOGS_YAML, encoding="utf-8")
        self.kernel.reload()
        self.assertEqual(len(self.kernel.history()), 1)

    def test_reload_applies_new_permissions(self) -> None:
        self.file.write_text(BASE_YAML.replace("  deploy: true\n", "  deploy: false\n"),
                             encoding="utf-8")
        self.kernel.reload()
        result = self.kernel.run("deploy to staging")
        self.assertFalse(result.success)
        self.assertIn("not allowed", result.failure["cause"])


class ReloadApiTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "baygon.yaml"
        self.file.write_text(BASE_YAML, encoding="utf-8")
        kernel = Kernel.start(tmp.name)
        self.server = make_server(kernel, host="127.0.0.1", port=0, token="tok")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _post(self, path: str, token: str | None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", path, body="{}", headers=headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_reload_endpoint_requires_auth_and_reloads(self) -> None:
        status, _ = self._post("/reload", token=None)
        self.assertEqual(status, 401)
        self.file.write_text(WITH_LOGS_YAML, encoding="utf-8")
        status, data = self._post("/reload", token="tok")
        self.assertEqual(status, 200)
        self.assertTrue(data["reloaded"])
        self.assertIn("logs", data["capabilities"])


if __name__ == "__main__":
    unittest.main()
