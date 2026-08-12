"""TDD — generic chat-completions adapter for the AI capability.

One adapter covers every provider exposing the de-facto standard
`/chat/completions` API: DeepSeek, Ollama (Llama, Qwen, ...), vLLM,
Mistral, Groq, LM Studio... — including fully local open-source models.
Chapter 3 lists DeepSeek, Qwen and "Modèle local" explicitly. No vendor
default (ENF-019): base_url and model are required; the API key is
optional because local endpoints need none.
"""

import os
import socket
import time
import unittest
from typing import Any
from unittest import mock

from baygon_plugins.openai_compat_ai import OpenAICompatibleAI


class FakeCompat(OpenAICompatibleAI):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.response: dict[str, Any] = {
            "choices": [{"message": {"content": "réponse du modèle"}}]
        }

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        self.posts.append((url, payload, headers))
        return self.response


class OpenAICompatibleAITest(unittest.TestCase):
    def test_deepseek_style_configuration(self) -> None:
        os.environ["DSTEST_KEY"] = "sk-deepseek"
        self.addCleanup(os.environ.pop, "DSTEST_KEY", None)
        adapter = FakeCompat({
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key_env": "DSTEST_KEY",
        })
        answer = adapter.complete("Diagnostique l'incident")
        url, payload, headers = adapter.posts[0]
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["messages"][0]["content"], "Diagnostique l'incident")
        self.assertEqual(headers["Authorization"], "Bearer sk-deepseek")
        self.assertEqual(answer, "réponse du modèle")

    def test_local_llama_via_ollama_needs_no_api_key(self) -> None:
        adapter = FakeCompat({
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
        })
        self.assertTrue(adapter.health_check())
        adapter.complete("hello")
        _, payload, headers = adapter.posts[0]
        self.assertEqual(payload["model"], "llama3")
        self.assertNotIn("Authorization", headers)

    def test_context_is_included_in_the_prompt(self) -> None:
        adapter = FakeCompat({"base_url": "http://localhost:11434/v1", "model": "qwen2"})
        adapter.complete("Diagnose", context={"1": {"latency_ms": 4800}})
        _, payload, _ = adapter.posts[0]
        self.assertIn("latency_ms", payload["messages"][0]["content"])

    def test_no_vendor_default_base_url_and_model_are_required(self) -> None:
        self.assertFalse(FakeCompat({}).health_check())
        self.assertFalse(FakeCompat({"base_url": "http://x"}).health_check())
        with self.assertRaisesRegex(ValueError, "model"):
            FakeCompat({"base_url": "http://x"}).complete("hello")

    def test_declared_key_env_must_be_set_for_health(self) -> None:
        os.environ.pop("DSTEST_ABSENT", None)
        adapter = FakeCompat({
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key_env": "DSTEST_ABSENT",
        })
        self.assertFalse(adapter.health_check())


def closed_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ReachabilityTest(unittest.TestCase):
    """An endpoint out of reach must be said so in seconds, not minutes.

    One timeout cannot serve both purposes. A local model legitimately
    takes a minute or more to compose an answer, so the response budget
    has to stay generous. Reaching the endpoint at all either works
    within seconds or never will — which is what an operator away from
    the machine hosting the model runs into.
    """

    def _adapter(self, **options: Any) -> OpenAICompatibleAI:
        port = closed_port()
        adapter = OpenAICompatibleAI({
            "base_url": f"http://127.0.0.1:{port}/v1",
            "model": "peu-importe",
            **options,
        })
        adapter.port = port  # type: ignore[attr-defined]
        return adapter

    def test_an_unreachable_endpoint_is_named_and_refused(self) -> None:
        """Our own guard must fire, not urlopen's expiry.

        The two are told apart by the exception: a RuntimeError naming
        the endpoint means we gave up on purpose, a URLError means we
        waited out the response budget.
        """
        adapter = self._adapter(connect_timeout_seconds=0.5)
        with self.assertRaises(RuntimeError) as raised:
            adapter.complete("bonjour")
        message = str(raised.exception)
        self.assertIn(str(adapter.port), message)  # type: ignore[attr-defined]
        self.assertIn("unreachable", message)
        self.assertIn("without AI", message, "the message must offer a way out")

    def test_the_wait_is_the_connect_budget_not_the_response_budget(self) -> None:
        adapter = self._adapter(connect_timeout_seconds=0.5, timeout_seconds=600)
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            adapter.complete("bonjour")
        self.assertLess(
            time.monotonic() - started, 30,
            "giving up must cost the connect timeout, not the response timeout",
        )

    def test_freshness_degrades_instead_of_hanging(self) -> None:
        """`baygon models` must stay usable with an endpoint out of reach."""
        described = self._adapter(connect_timeout_seconds=0.5).describe()
        self.assertIsNone(described["up_to_date"])
        self.assertFalse(described["reachable"])

    def test_an_endpoint_that_answers_is_reported_reachable(self) -> None:
        class Listing(FakeCompat):
            def _get_json(self, url: str, headers: dict[str, str]) -> Any:
                return {"data": [{"id": "m"}]}

        described = Listing({"base_url": "http://x", "model": "m"}).describe()
        self.assertTrue(described["reachable"])
        self.assertTrue(described["up_to_date"])

    def test_both_budgets_are_declarable_with_sane_defaults(self) -> None:
        default = FakeCompat({"base_url": "http://x", "model": "m"})
        self.assertEqual(default.response_timeout(), 120.0)
        self.assertEqual(default.connect_timeout(), 5.0)
        tuned = FakeCompat({
            "base_url": "http://x", "model": "m",
            "timeout_seconds": 30, "connect_timeout_seconds": 1,
        })
        self.assertEqual(tuned.response_timeout(), 30.0)
        self.assertEqual(tuned.connect_timeout(), 1.0)

    def test_a_proxy_turns_the_direct_probe_off(self) -> None:
        """Behind a proxy, the endpoint is not who we would connect to.

        Probing it directly would answer the wrong question and refuse a
        setup that actually works — the very networks an operator meets
        away from home.
        """
        adapter = FakeCompat({"base_url": "http://ailleurs.invalid/v1", "model": "m"})
        with mock.patch.dict(os.environ, {"http_proxy": "http://proxy.invalid:3128"}):
            self.assertFalse(adapter.probes_directly())
        with mock.patch.dict(os.environ, {"http_proxy": "", "no_proxy": "*"}, clear=False):
            os.environ.pop("http_proxy", None)
            self.assertTrue(adapter.probes_directly())

    def test_the_probe_can_be_switched_off(self) -> None:
        adapter = FakeCompat({
            "base_url": "http://x", "model": "m", "connect_timeout_seconds": 0,
        })
        self.assertFalse(adapter.probes_directly())


if __name__ == "__main__":
    unittest.main()
