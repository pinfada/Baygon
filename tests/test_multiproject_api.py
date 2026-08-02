"""TDD — serving several projects from one Shell (EF-001, EF-004).

From a phone there is a single entry point, but possibly several
applications behind it. The API must therefore route each request to
the right project — by the name in the intention, or explicitly — and
say so clearly when the target is ambiguous.
"""

import http.client
import json
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon.core.projects import ProjectManager
from baygon.shell.api import make_server


def _project_yaml(name: str) -> str:
    return textwrap.dedent(
        f"""
        version: 1
        project: {{name: {name}}}
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
          development: {{}}
          staging: {{}}
          production: {{}}
        permissions:
          deploy: true
          production: true
        """
    )


class MultiProjectApiTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in ("jiyufit", "baygonweb"):
            (root / name).mkdir()
            (root / name / "baygon.yaml").write_text(_project_yaml(name), encoding="utf-8")
        manager = ProjectManager.discover(root)
        self.server = make_server(manager, host="127.0.0.1", port=0, token="tok")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _request(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json",
                              "Authorization": "Bearer tok"})
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_projects_endpoint_lists_the_applications(self) -> None:
        status, data = self._request("GET", "/projects")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(data), ["baygonweb", "jiyufit"])

    def test_intent_naming_the_application_routes_to_it(self) -> None:
        status, data = self._request(
            "POST", "/run", {"intent": "Déploie JiyuFit en staging"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        # The audit trail of the other project stays untouched.
        status, other = self._request("GET", "/history?project=baygonweb")
        self.assertEqual(other, [])

    def test_explicit_project_field_wins(self) -> None:
        status, data = self._request(
            "POST", "/run", {"intent": "deploy to staging", "project": "baygonweb"}
        )
        self.assertEqual(status, 200)
        status, history = self._request("GET", "/history?project=baygonweb")
        self.assertEqual(len(history), 1)

    def test_ambiguous_target_is_refused_with_the_known_list(self) -> None:
        status, data = self._request("POST", "/run", {"intent": "deploy to staging"})
        self.assertEqual(status, 400)
        self.assertIn("jiyufit", data["error"])

    def test_read_endpoints_accept_a_project_query(self) -> None:
        status, data = self._request("GET", "/capabilities?project=jiyufit")
        self.assertEqual(status, 200)
        self.assertIn("deployment", data)
        status, data = self._request("GET", "/context?project=baygonweb")
        self.assertEqual(data["project"]["name"], "baygonweb")

    def test_read_endpoint_without_project_is_refused_when_ambiguous(self) -> None:
        status, data = self._request("GET", "/capabilities")
        self.assertEqual(status, 400)
        self.assertIn("jiyufit", data["error"])

    def test_health_stays_open_and_lists_the_projects(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/health")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(sorted(data["projects"]), ["baygonweb", "jiyufit"])

    def test_web_page_offers_the_project_choice(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode("utf-8")
        self.assertIn("/projects", page)


class SingleProjectStaysSimpleTest(unittest.TestCase):
    """One project: nothing to choose, nothing changes."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(_project_yaml("solo"), encoding="utf-8")
        kernel = Kernel.start(tmp.name)
        self.server = make_server(kernel, host="127.0.0.1", port=0, token="tok")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _request(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json",
                              "Authorization": "Bearer tok"})
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))

    def test_no_project_needed_anywhere(self) -> None:
        status, data = self._request("GET", "/capabilities")
        self.assertEqual(status, 200)
        status, data = self._request("POST", "/run", {"intent": "deploy to staging"})
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])

    def test_projects_endpoint_lists_the_single_project(self) -> None:
        status, data = self._request("GET", "/projects")
        self.assertEqual(data, ["solo"])


class ServeCommandTest(unittest.TestCase):
    def test_multi_project_serve_does_not_fail_at_startup(self) -> None:
        """`baygon --projects DIR serve` must start, not resolve a project."""
        import argparse

        from baygon.shell.cli import _select_target

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in ("alpha", "beta"):
            (root / name).mkdir()
            (root / name / "baygon.yaml").write_text(_project_yaml(name), encoding="utf-8")
        args = argparse.Namespace(
            projects=str(root), project=None, command="serve", file="baygon.yaml"
        )
        target = _select_target(args)
        self.assertEqual(sorted(target.projects()), ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
