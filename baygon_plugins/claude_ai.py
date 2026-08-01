"""AI capability backed by Claude (Anthropic API).

Second implementation of the `ai` contract, next to OfflineAI: swapping
models only ever touches the `ai` block of baygon.yaml (EF-013), and
the AI stays optional (EF-014) — if the SDK or the API key is missing,
the implementation is simply marked unavailable and Baygon keeps
working in degraded mode.

Declared in baygon.yaml as:

    ai:
      default: claude
      providers:
        claude:
          type: ai
          plugin: baygon_plugins.claude_ai:ClaudeAI
          options:
            model: claude-opus-5      # optional
            max_tokens: 16000         # optional
            api_key_env: ANTHROPIC_API_KEY  # optional

Requires the optional `anthropic` package. The key is read from the
environment (never from configuration — EF-011).
"""

from __future__ import annotations

import json
import os
from typing import Any

from baygon.capabilities import AICapability

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000


class ClaudeAI(AICapability):
    identifier = "claude"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    def _client(self) -> Any:
        """Build the Anthropic client. Single seam, faked in tests."""
        import anthropic

        return anthropic.Anthropic(api_key=os.environ[self._key_env()])

    def _key_env(self) -> str:
        return str(self.config.get("api_key_env", "ANTHROPIC_API_KEY"))

    def _sdk_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def health_check(self) -> bool:
        return bool(os.environ.get(self._key_env())) and self._sdk_available()

    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str:
        content = prompt
        if context:
            content += "\n\nAvailable context:\n" + json.dumps(
                context, ensure_ascii=False, default=str, indent=2
            )
        response = self._client().messages.create(
            model=str(self.config.get("model", DEFAULT_MODEL)),
            max_tokens=int(self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            messages=[{"role": "user", "content": content}],
        )
        # Safety classifiers may decline: check stop_reason before content.
        if response.stop_reason == "refusal":
            raise RuntimeError("the model refused this request (stop_reason=refusal)")
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
