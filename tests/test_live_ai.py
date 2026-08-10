"""Live AI — the same code paths, against a model that really answers.

Every other AI test in this suite uses a double, which proves that
Baygon calls the adapter correctly but never that a real model's reply
survives the trip. A real model returns prose, punctuation, blank first
lines, reasoning blocks and occasional refusals; the promises that
matter — Baygon never invents an action (Article 5), the model is never
a dependency (EF-014), an unreachable provider degrades rather than
breaks (ENF-006) — are only truly demonstrated against one.

These tests are **opt-in**: they are skipped unless an endpoint is
declared, so the normal suite and CI stay hermetic and fast.

    # any OpenAI-compatible endpoint: Ollama, vLLM, DeepSeek, Groq...
    export BAYGON_LIVE_AI_BASE_URL=http://localhost:11434/v1
    export BAYGON_LIVE_AI_MODEL=deepseek-r1:8b
    export BAYGON_LIVE_AI_KEY_ENV=DEEPSEEK_API_KEY   # optional
    python -m unittest tests.test_live_ai -v

A real model takes seconds to answer, so this module is deliberately
frugal: it asks as few completions as the assertions require.

Assertions are about **contracts, never about a particular answer**. A
model is free to classify "mets la nouvelle version en ligne" as it
sees fit; what must hold is that whatever comes back is either one of
the known intentions or a clean refusal.
"""

from __future__ import annotations

import os
import socket
import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.errors import UnknownIntentError
from baygon.core.kernel import Kernel
from baygon_plugins.openai_compat_ai import OpenAICompatibleAI

BASE_URL = os.environ.get("BAYGON_LIVE_AI_BASE_URL")
MODEL = os.environ.get("BAYGON_LIVE_AI_MODEL")
KEY_ENV = os.environ.get("BAYGON_LIVE_AI_KEY_ENV")

LIVE = bool(BASE_URL and MODEL)
WHY_SKIPPED = (
    "live AI not configured: set BAYGON_LIVE_AI_BASE_URL and BAYGON_LIVE_AI_MODEL"
)

#: A phrasing no deterministic rule matches, so the model is the only
#: way this request can ever resolve.
UNRULED = "j'aimerais mettre la nouvelle version en ligne"


def _live_yaml(base_url: str, model: str, key_env: str | None) -> str:
    key_line = f"\n            api_key_env: {key_env}" if key_env else ""
    return textwrap.dedent(
        f"""
        version: 1
        project:
          name: live
        providers:
          logging:
            type: logs
            plugin: tests.helpers:FakeLogs
            default: true
          monitoring:
            type: metrics
            plugin: tests.helpers:FakeMetrics
            default: true
          cloud:
            type: deployment
            plugin: tests.helpers:FakeDeployment
            default: true
        environments:
          development: {{}}
          staging: {{}}
          production: {{}}
        ai:
          default: live
          providers:
            live:
              type: ai
              plugin: baygon_plugins.openai_compat_ai:OpenAICompatibleAI
              options:
                base_url: {base_url}
                model: {model}{key_line}
        permissions:
          deploy: true
        """
    )


def _closed_port() -> int:
    """A port nothing is listening on — a real connection refusal."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@unittest.skipUnless(LIVE, WHY_SKIPPED)
class LiveModelTest(unittest.TestCase):
    """The adapter, against an endpoint that really serves a model."""

    def setUp(self) -> None:
        self.adapter = OpenAICompatibleAI(
            {"base_url": BASE_URL, "model": MODEL, "api_key_env": KEY_ENV}
        )

    def test_the_endpoint_confirms_it_serves_the_declared_model(self) -> None:
        described = self.adapter.describe()
        self.assertEqual(described["model"], MODEL)
        self.assertTrue(described["known_models"], "the endpoint listed no model")
        self.assertTrue(
            described["up_to_date"],
            f"{MODEL!r} is not served by {BASE_URL!r}; declared models: "
            f"{described['known_models']}",
        )

    def test_a_real_completion_comes_back_as_usable_text(self) -> None:
        answer = self.adapter.complete("Answer with the single word: ready")
        self.assertIsInstance(answer, str)
        self.assertTrue(
            answer.strip(),
            "the model answered with nothing — a reasoning model may have put "
            "everything in a field the adapter does not read",
        )


@unittest.skipUnless(LIVE, WHY_SKIPPED)
class LiveIntentResolutionTest(unittest.TestCase):
    """Article 5: Baygon decides which tools to use, it never invents one."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(
            _live_yaml(str(BASE_URL), str(MODEL), KEY_ENV), encoding="utf-8"
        )
        self.kernel = Kernel.start(tmp.name)

    def test_the_model_only_ever_yields_a_known_intention(self) -> None:
        known = self.kernel.intent_engine.supported_intents()
        try:
            plan = self.kernel.plan(UNRULED)
        except UnknownIntentError:
            return  # declining is a valid, documented outcome
        self.assertIn(plan.intent.name, known)
        self.assertEqual(
            plan.intent.resolved_by, "ai",
            "no rule matches this phrasing, so the model resolved it",
        )
        # Transparency (Article 8): the plan says the model decided.
        self.assertIn("AI model", plan.explain())

    def test_deterministic_mode_never_reaches_the_live_model(self) -> None:
        """EF-014, demonstrated rather than mocked.

        The same phrasing resolves with the model and does not resolve
        without it. Since only the model can resolve it, a refusal is
        proof that nothing was asked of it.
        """
        try:
            plan = self.kernel.plan(UNRULED, ai=True)
        except UnknownIntentError:
            self.skipTest("the live model declined this phrasing; nothing to compare")
        self.assertEqual(plan.intent.resolved_by, "ai")

        with self.assertRaises(UnknownIntentError):
            self.kernel.plan(UNRULED, ai=False)

    def test_a_full_diagnosis_runs_through_the_live_model(self) -> None:
        """The heavy path: gather context, then have it really analysed."""
        result = self.kernel.run("pourquoi la production est lente ?")
        self.assertTrue(result.success, result.failure)
        ai_steps = [step for step in result.steps if step.step.capability == "ai"]
        self.assertEqual(len(ai_steps), 1)
        analysis = ai_steps[0].output
        self.assertTrue(str(analysis).strip(), "the model returned an empty analysis")
        # ENF-008: a real call takes real time, and it is reported.
        self.assertGreater(ai_steps[0].duration_ms, 0.0)


class UnreachableProviderTest(unittest.TestCase):
    """ENF-006, against a real refused connection rather than a double.

    Needs no model and no configuration: nothing is listening, so the
    socket really fails. This is the case operators actually hit — the
    endpoint is down, the laptop is offline — and it must degrade.
    """

    def setUp(self) -> None:
        self.dead = f"http://127.0.0.1:{_closed_port()}/v1"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(
            _live_yaml(self.dead, "any-model", None), encoding="utf-8"
        )
        self.kernel = Kernel.start(tmp.name)

    def test_freshness_is_unknown_rather_than_an_error(self) -> None:
        described = OpenAICompatibleAI(
            {"base_url": self.dead, "model": "any-model"}
        ).describe()
        self.assertIsNone(described["up_to_date"])
        self.assertEqual(described["known_models"], [])

    def test_models_listing_survives_an_unreachable_endpoint(self) -> None:
        entries = self.kernel.models()
        self.assertEqual([entry["name"] for entry in entries], ["live"])
        self.assertIsNone(entries[0]["up_to_date"])

    def test_intent_resolution_degrades_to_the_normal_error(self) -> None:
        """An unreachable model must not turn into a stack trace."""
        with self.assertRaises(UnknownIntentError):
            self.kernel.plan(UNRULED)

    def test_the_rules_keep_working_without_any_model(self) -> None:
        """EF-014: the essential commands never needed the model."""
        plan = self.kernel.plan("deploy to staging")
        self.assertEqual(plan.intent.name, "DeployProject")
        self.assertEqual(plan.intent.resolved_by, "rules")

    def test_a_diagnosis_still_gathers_its_context(self) -> None:
        """ENF-006: degraded, not broken — the facts are still collected."""
        result = self.kernel.run("pourquoi la production est lente ?")
        gathered = [step.step.capability for step in result.steps if step.success]
        self.assertIn("logs", gathered)
        self.assertIn("metrics", gathered)


if __name__ == "__main__":
    unittest.main()
