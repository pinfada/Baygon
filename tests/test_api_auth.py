"""TDD — API authentication (Article 7, ENF-005).

Security is on by default: every access is authenticated. The token is
never stored in clear text in baygon.yaml — it comes from the process
environment or from the secrets capability.
"""

import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.shell.api import make_server, resolve_api_token
from baygon.shell.cli import main
from tests.helpers import MINIMAL_YAML

AUTH_YAML = MINIMAL_YAML.replace(
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


class AuthenticatedApiTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(AUTH_YAML, encoding="utf-8")
        self.dir = tmp.name
        kernel = Kernel.start(tmp.name)
        self.server = make_server(kernel, host="127.0.0.1", port=0, token="s3cret-token")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _request(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_request_without_token_is_401(self) -> None:
        status, data = self._request("GET", "/capabilities")
        self.assertEqual(status, 401)
        self.assertIn("error", data)

    def test_request_with_wrong_token_is_401(self) -> None:
        status, _ = self._request("GET", "/capabilities", token="wrong")
        self.assertEqual(status, 401)
        status, _ = self._request("POST", "/run", {"intent": "deploy to staging"}, token="wrong")
        self.assertEqual(status, 401)

    def test_request_with_valid_token_succeeds(self) -> None:
        status, data = self._request("GET", "/capabilities", token="s3cret-token")
        self.assertEqual(status, 200)
        self.assertIn("deployment", data)
        status, data = self._request(
            "POST", "/run", {"intent": "deploy to staging"}, token="s3cret-token"
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])

    def test_health_stays_open_for_liveness(self) -> None:
        status, data = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")


class TokenResolutionTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = AUTH_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def test_token_from_environment(self) -> None:
        os.environ["BAYGON_TEST_TOKEN"] = "from-env"
        self.addCleanup(os.environ.pop, "BAYGON_TEST_TOKEN", None)
        token = resolve_api_token(self._kernel(), env_var="BAYGON_TEST_TOKEN")
        self.assertEqual(token, "from-env")

    def test_token_from_secrets_capability(self) -> None:
        yaml = AUTH_YAML.replace(
            "providers:",
            "providers:\n"
            "  vault:\n"
            "    type: secrets\n"
            "    plugin: baygon_plugins.env_secrets:EnvSecrets\n"
            "    default: true\n"
            "    options:\n"
            "      prefix: BAYGONTEST_",
            1,
        )
        os.environ["BAYGONTEST_API_TOKEN"] = "from-secrets"
        self.addCleanup(os.environ.pop, "BAYGONTEST_API_TOKEN", None)
        token = resolve_api_token(self._kernel(yaml), env_var="BAYGON_ABSENT_VAR")
        self.assertEqual(token, "from-secrets")

    def test_no_token_resolves_to_none(self) -> None:
        token = resolve_api_token(self._kernel(), env_var="BAYGON_ABSENT_VAR")
        self.assertIsNone(token)

    def test_cli_serve_refuses_to_start_without_token(self) -> None:
        # Security by default: no token and no explicit --insecure -> error.
        import contextlib
        import io

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        file = Path(tmp.name) / "baygon.yaml"
        file.write_text(AUTH_YAML, encoding="utf-8")
        os.environ.pop("BAYGON_API_TOKEN", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["-f", str(file), "serve", "--port", "0"])
        self.assertEqual(code, 2)
        self.assertIn("token", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
