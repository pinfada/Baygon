"""TDD — Claude adapter for the AI capability.

Second implementation of the `ai` contract (next to OfflineAI), proving
model interchangeability (EF-013): swapping models only touches the
`ai` block of baygon.yaml, never the core.

The Anthropic SDK client is built behind a single overridable seam
(`_client`), faked here — tests run offline and without the SDK.
"""

import os
import unittest
from types import SimpleNamespace
from typing import Any

from baygon_plugins.claude_ai import ClaudeAI


class RecordingClient:
    """Stands in for anthropic.Anthropic()."""

    def __init__(self, response: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self._response = response

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _response(stop_reason: str = "end_turn", texts: tuple[str, ...] = ("Hello",)) -> Any:
    content = [SimpleNamespace(type="text", text=text) for text in texts]
    content.insert(0, SimpleNamespace(type="thinking", thinking=""))
    return SimpleNamespace(stop_reason=stop_reason, content=content)


class FakeClaude(ClaudeAI):
    def __init__(self, config: dict[str, Any] | None = None, response: Any = None) -> None:
        super().__init__(config)
        self.client = RecordingClient(response or _response())

    def _client(self) -> Any:
        return self.client

    def _sdk_available(self) -> bool:
        # Tests run without the optional `anthropic` package installed.
        return True


class ClaudeAITest(unittest.TestCase):
    def test_complete_returns_joined_text_blocks(self) -> None:
        adapter = FakeClaude(response=_response(texts=("Part one. ", "Part two.")))
        self.assertEqual(adapter.complete("Diagnose the incident"), "Part one. Part two.")

    def test_default_model_is_claude_opus_5(self) -> None:
        adapter = FakeClaude()
        adapter.complete("hello")
        self.assertEqual(adapter.client.calls[0]["model"], "claude-opus-5")

    def test_model_comes_from_configuration_when_declared(self) -> None:
        adapter = FakeClaude({"model": "claude-haiku-4-5", "max_tokens": 512})
        adapter.complete("hello")
        call = adapter.client.calls[0]
        self.assertEqual(call["model"], "claude-haiku-4-5")
        self.assertEqual(call["max_tokens"], 512)

    def test_context_is_included_in_the_prompt(self) -> None:
        adapter = FakeClaude()
        adapter.complete("Diagnose", context={"1": ["log line"], "2": {"latency_ms": 48}})
        content = adapter.client.calls[0]["messages"][0]["content"]
        self.assertIn("Diagnose", content)
        self.assertIn("log line", content)
        self.assertIn("latency_ms", content)

    def test_refusal_stop_reason_raises_instead_of_empty_answer(self) -> None:
        adapter = FakeClaude(response=_response(stop_reason="refusal", texts=()))
        with self.assertRaisesRegex(RuntimeError, "refus"):
            adapter.complete("hello")

    def test_health_check_requires_api_key(self) -> None:
        os.environ.pop("BAYGON_TEST_ANTHROPIC_KEY", None)
        adapter = FakeClaude({"api_key_env": "BAYGON_TEST_ANTHROPIC_KEY"})
        self.assertFalse(adapter.health_check())
        os.environ["BAYGON_TEST_ANTHROPIC_KEY"] = "sk-test"
        self.addCleanup(os.environ.pop, "BAYGON_TEST_ANTHROPIC_KEY", None)
        self.assertTrue(adapter.health_check())


if __name__ == "__main__":
    unittest.main()
