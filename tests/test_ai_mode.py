"""TDD — choosing the AI mode and the model at connection time.

The configuration declares which models are available (EF-015); the
user picks among them per session — that is exactly rule 1 of the
Capability Registry ("implémentation explicitement demandée").

Three things must hold:
  - a session can run entirely without AI (EF-014);
  - a session can target one declared model by name;
  - Baygon can say whether that model is still current, without ever
    making freshness a hard dependency (ENF-006: degrade cleanly).
"""

import http.client
import json
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from typing import Any

from baygon.core.errors import CapabilityUnavailableError, UnknownIntentError
from baygon.core.kernel import Kernel
from baygon.shell.api import make_server
from tests.helpers import ClassifierAI

TWO_MODELS_YAML = textwrap.dedent(
    """
    version: 1
    project: {name: demo}
    providers: {}
    environments:
      development: {}
      staging: {}
      production: {}
    ai:
      default: fast
      providers:
        fast:
          type: ai
          plugin: tests.helpers:ClassifierAI
        deep:
          type: ai
          plugin: tests.helpers:SecondClassifierAI
    """
)


class SessionAiModeTest(unittest.TestCase):
    def setUp(self) -> None:
        ClassifierAI.prompts = []
        ClassifierAI.answer = "Diagnose"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(TWO_MODELS_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_ai_disabled_never_calls_a_model(self) -> None:
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan("le p99 du checkout est monté à 3 secondes", ai=False)
        self.assertEqual(ClassifierAI.prompts, [])

    def test_ai_enabled_by_default_classifies(self) -> None:
        plan = self.kernel.plan("le p99 du checkout est monté à 3 secondes")
        self.assertEqual(plan.intent.resolved_by, "ai")
        self.assertEqual(len(ClassifierAI.prompts), 1)

    def test_choosing_a_declared_model_routes_to_it(self) -> None:
        from tests.helpers import SecondClassifierAI

        SecondClassifierAI.prompts = []
        SecondClassifierAI.answer = "ShowMetrics"
        plan = self.kernel.plan(
            "le p99 du checkout est monté à 3 secondes", ai_model="deep"
        )
        self.assertEqual(plan.intent.name, "ShowMetrics")
        self.assertEqual(len(SecondClassifierAI.prompts), 1)
        self.assertEqual(ClassifierAI.prompts, [])  # the default was not used

    def test_serialized_plan_says_how_the_intent_was_resolved(self) -> None:
        # Article 8: API and web clients must see it too, not just the CLI.
        by_rules = self.kernel.plan("pourquoi la prod est lente ?").to_dict()
        self.assertEqual(by_rules["intent"]["resolved_by"], "rules")
        by_ai = self.kernel.plan("le p99 du checkout est monté à 3 secondes").to_dict()
        self.assertEqual(by_ai["intent"]["resolved_by"], "ai")

    def test_unknown_model_is_refused_with_the_known_list(self) -> None:
        with self.assertRaises(CapabilityUnavailableError) as ctx:
            self.kernel.plan("peu importe", ai_model="gpt-inexistant")
        self.assertIn("gpt-inexistant", str(ctx.exception))

    def test_ai_steps_target_the_chosen_model(self) -> None:
        plan = self.kernel.plan("analyse l'incident en production", ai_model="deep")
        ai_steps = [s for s in plan.steps if s.capability == "ai"]
        self.assertEqual(len(ai_steps), 1)
        self.assertEqual(ai_steps[0].implementation, "deep")

    def test_models_lists_what_the_session_may_choose(self) -> None:
        models = {entry["name"]: entry for entry in self.kernel.models()}
        # Selection uses the names declared in baygon.yaml, not the
        # adapter class: one generic adapter may back several models.
        self.assertEqual(sorted(models), ["deep", "fast"])
        self.assertEqual(models["fast"]["adapter"], "classifier-ai")
        self.assertEqual(models["fast"]["state"], "ACTIVE")
        # Freshness is reported when the adapter can tell, else None.
        self.assertIn("up_to_date", models["fast"])


class ModelFreshnessTest(unittest.TestCase):
    def test_compatible_adapter_reports_whether_the_model_is_current(self) -> None:
        from baygon_plugins.openai_compat_ai import OpenAICompatibleAI

        class FakeCompat(OpenAICompatibleAI):
            listed = {"data": [{"id": "llama3"}, {"id": "qwen2"}]}

            def _get_json(self, url: str, headers: dict[str, str]) -> Any:
                return self.listed

        fresh = FakeCompat({"base_url": "http://localhost:11434/v1", "model": "llama3"})
        described = fresh.describe()
        self.assertEqual(described["model"], "llama3")
        self.assertTrue(described["up_to_date"])
        self.assertIn("qwen2", described["known_models"])

        stale = FakeCompat({"base_url": "http://localhost:11434/v1", "model": "llama2"})
        self.assertFalse(stale.describe()["up_to_date"])

    def test_unreachable_endpoint_degrades_to_unknown(self) -> None:
        from baygon_plugins.openai_compat_ai import OpenAICompatibleAI

        class BrokenCompat(OpenAICompatibleAI):
            def _get_json(self, url: str, headers: dict[str, str]) -> Any:
                raise RuntimeError("endpoint down")

        adapter = BrokenCompat({"base_url": "http://x", "model": "llama3"})
        described = adapter.describe()
        self.assertIsNone(described["up_to_date"])  # unknown, not an error
        self.assertEqual(described["model"], "llama3")


class SessionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        ClassifierAI.prompts = []
        ClassifierAI.answer = "Diagnose"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(TWO_MODELS_YAML, encoding="utf-8")
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

    def test_models_endpoint_lists_the_choices(self) -> None:
        status, data = self._request("GET", "/models")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(entry["name"] for entry in data), ["deep", "fast"])

    def test_session_can_turn_ai_off(self) -> None:
        status, data = self._request(
            "POST", "/plan", {"intent": "le p99 du checkout est monté à 3 secondes", "ai": False}
        )
        self.assertEqual(status, 400)
        self.assertEqual(ClassifierAI.prompts, [])

    def test_session_can_choose_the_model(self) -> None:
        from tests.helpers import SecondClassifierAI

        SecondClassifierAI.prompts = []
        SecondClassifierAI.answer = "ShowLogs"
        status, data = self._request(
            "POST", "/plan",
            {"intent": "le p99 du checkout est monté à 3 secondes", "model": "deep"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["plan"]["intent"]["name"], "ShowLogs")
        self.assertEqual(len(SecondClassifierAI.prompts), 1)

    def test_cli_models_listing_renders(self) -> None:
        import contextlib
        import io

        from baygon.shell.cli import main

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        file = Path(tmp.name) / "baygon.yaml"
        file.write_text(TWO_MODELS_YAML, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["-f", str(file), "models"])
        self.assertEqual(code, 0)
        self.assertIn("fast", out.getvalue())
        self.assertIn("deep", out.getvalue())

    def test_web_page_offers_the_mode_and_model_choice(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        page = conn.getresponse().read().decode("utf-8")
        self.assertIn("/models", page)      # populates the choice
        self.assertIn("Sans IA", page)      # the no-AI mode is offered


if __name__ == "__main__":
    unittest.main()
