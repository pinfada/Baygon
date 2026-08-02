"""AI capability backed by any chat-completions-compatible endpoint.

One adapter for every provider speaking the de-facto standard
`/chat/completions` API — including fully open-source and local models
(chapter 3 lists DeepSeek, Qwen and "Modèle local" explicitly):

    DeepSeek     base_url: https://api.deepseek.com      model: deepseek-chat
    Ollama       base_url: http://localhost:11434/v1     model: llama3, qwen2, ...
    vLLM         base_url: http://localhost:8000/v1      model: <served model>
    Mistral      base_url: https://api.mistral.ai/v1     model: mistral-large-latest
    Groq         base_url: https://api.groq.com/openai/v1  model: llama-3.1-70b-versatile

No vendor default (ENF-019): `base_url` and `model` are required. The
API key is optional — local endpoints need none; when a provider does,
declare `api_key_env` and the key is read from the environment
(EF-011), never from configuration.

    ai:
      default: deepseek
      providers:
        deepseek:
          type: ai
          plugin: baygon_plugins.openai_compat_ai:OpenAICompatibleAI
          options:
            base_url: https://api.deepseek.com
            model: deepseek-chat
            api_key_env: DEEPSEEK_API_KEY
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from baygon.capabilities import AICapability


class OpenAICompatibleAI(AICapability):
    identifier = "openai-compatible"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "baygon", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    # ------------------------------------------------------------------

    def _require(self, key: str) -> str:
        value = self.config.get(key)
        if not value:
            raise ValueError(
                f"option {key!r} is required: declare your endpoint and model in "
                "baygon.yaml (no vendor default)"
            )
        return str(value)

    def health_check(self) -> bool:
        if not (self.config.get("base_url") and self.config.get("model")):
            return False
        key_env = self.config.get("api_key_env")
        if key_env and not os.environ.get(str(key_env)):
            return False
        return True

    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str:
        base_url = self._require("base_url").rstrip("/")
        model = self._require("model")
        content = prompt
        if context:
            content += "\n\nAvailable context:\n" + json.dumps(
                context, ensure_ascii=False, default=str, indent=2
            )
        headers: dict[str, str] = {}
        key_env = self.config.get("api_key_env")
        if key_env:
            key = os.environ.get(str(key_env))
            if not key:
                raise RuntimeError(f"environment variable {key_env!r} is not set")
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": model,
            "max_tokens": int(self.config.get("max_tokens", 4096)),
            "messages": [{"role": "user", "content": content}],
        }
        data = self._post_json(f"{base_url}/chat/completions", payload, headers)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("the model returned no choices")
        return str(choices[0].get("message", {}).get("content", ""))
