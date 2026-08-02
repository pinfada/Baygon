"""TDD — generic chat-completions adapter for the AI capability.

One adapter covers every provider exposing the de-facto standard
`/chat/completions` API: DeepSeek, Ollama (Llama, Qwen, ...), vLLM,
Mistral, Groq, LM Studio... — including fully local open-source models.
Chapter 3 lists DeepSeek, Qwen and "Modèle local" explicitly. No vendor
default (ENF-019): base_url and model are required; the API key is
optional because local endpoints need none.
"""

import os
import unittest
from typing import Any

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


if __name__ == "__main__":
    unittest.main()
