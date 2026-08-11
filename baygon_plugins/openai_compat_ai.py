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
import urllib.error
import urllib.request
from typing import Any

from baygon.capabilities import AICapability
from baygon_plugins import _http
from baygon_plugins._http import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    EndpointUnreachable,
)

#: How long a model may take to compose its answer. Generous on
#: purpose: a local reasoning model routinely needs a minute or more.
DEFAULT_TIMEOUT_SECONDS = 120.0
#: Freshness is informative, so its request never waits long.
LIST_TIMEOUT_SECONDS = 15.0
#: How much gathered context may accompany a prompt. Local models have
#: small windows (deepseek-r1:8b serves 4096 tokens); a 100-line Rails
#: log alone blows past it and the request is refused outright. The
#: budget is declarable (`max_context_chars`) per provider.
DEFAULT_MAX_CONTEXT_CHARS = 12_000


def _refusal_detail(error: urllib.error.HTTPError) -> str:
    """What the server actually said, not just its status line.

    Providers put the reason in the response body — Ollama nests it
    twice (`error.message` is itself a JSON error). Unwrap what can be
    unwrapped and keep the end, where the figures are.
    """
    try:
        detail = error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    for _ in range(2):
        try:
            data = json.loads(detail)
        except (ValueError, TypeError):
            break
        found = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(found, dict):
            found = found.get("message", "")
        if not found:
            break
        detail = str(found)
    return detail[-400:]


class OpenAICompatibleAI(AICapability):
    identifier = "openai-compatible"
    version = "0.1.0"
    author = "Baygon"
    license = "MIT"

    # ------------------------------------------------------------------
    # Transport — single overridable seam, faked in tests.
    # ------------------------------------------------------------------

    def _get_json(self, url: str, headers: dict[str, str]) -> Any:
        self.require_reachable()
        request = urllib.request.Request(
            url, headers={"User-Agent": "baygon", **headers}, method="GET"
        )
        with urllib.request.urlopen(request, timeout=LIST_TIMEOUT_SECONDS) as response:
            return json.load(response)

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        self.require_reachable()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "baygon", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.response_timeout()) as response:
            return json.load(response)

    # ------------------------------------------------------------------
    # Reaching the endpoint, kept separate from waiting for its answer.
    # ------------------------------------------------------------------

    def response_timeout(self) -> float:
        return float(self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))

    def connect_timeout(self) -> float:
        return float(
            self.config.get("connect_timeout_seconds", DEFAULT_CONNECT_TIMEOUT_SECONDS)
        )

    def endpoint(self) -> tuple[str, int]:
        return _http.endpoint_of(self.config.get("base_url", ""))

    def probes_directly(self) -> bool:
        return _http.probes_directly(
            self.config.get("base_url", ""), self.connect_timeout()
        )

    def require_reachable(self) -> None:
        """Give up on an out-of-reach endpoint in seconds, not minutes.

        The way out differs from the other adapters: a model is chosen
        per session, so the operator can pick another one — or none.
        """
        try:
            _http.require_reachable("AI", self.config.get("base_url", ""), self.connect_timeout())
        except EndpointUnreachable as exc:
            raise EndpointUnreachable(
                f"{exc}. Choose another declared model for this session, "
                "or run without AI"
            ) from exc

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

    def describe(self) -> dict[str, Any]:
        """Ask the endpoint which models it serves, to flag a stale one."""
        model = self.config.get("model")
        described: dict[str, Any] = {
            "identifier": self.identifier,
            "model": model,
            "up_to_date": None,
            "known_models": [],
            "reachable": None,
        }
        try:
            base_url = str(self.config["base_url"]).rstrip("/")
            data = self._get_json(f"{base_url}/models", self._auth_headers())
            known = [str(entry.get("id", "")) for entry in data.get("data", [])]
        except EndpointUnreachable:
            # Worth saying out loud rather than leaving as "unknown":
            # picking that model would only waste the operator's time.
            described["reachable"] = False
            return described
        except Exception:
            return described  # freshness unknown is not an error (ENF-006)
        described["known_models"] = known
        described["up_to_date"] = model in known
        described["reachable"] = True
        return described

    def _auth_headers(self) -> dict[str, str]:
        key_env = self.config.get("api_key_env")
        key = os.environ.get(str(key_env)) if key_env else None
        return {"Authorization": f"Bearer {key}"} if key else {}

    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str:
        base_url = self._require("base_url").rstrip("/")
        model = self._require("model")
        content = prompt
        if context:
            rendered = json.dumps(context, ensure_ascii=False, default=str, indent=2)
            budget = int(self.config.get("max_context_chars", DEFAULT_MAX_CONTEXT_CHARS))
            if len(rendered) > budget:
                # Keep the tail: logs put the recent — hence relevant —
                # lines at the end, and a visible cut beats a refusal.
                rendered = "…" + rendered[-budget:]
            content += "\n\nAvailable context:\n" + rendered
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
        try:
            data = self._post_json(f"{base_url}/chat/completions", payload, headers)
        except urllib.error.HTTPError as exc:
            # The server names the problem (context size, bad model…);
            # `HTTP Error 400` alone would hide the way out.
            detail = _refusal_detail(exc)
            raise RuntimeError(
                f"the AI endpoint answered HTTP {exc.code}"
                + (f": {detail}" if detail else "")
            ) from exc
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("the model returned no choices")
        message = choices[0].get("message", {})
        content = str(message.get("content", ""))
        if not content.strip():
            # Reasoning models spend completion tokens thinking before
            # answering; a budget that only covers the thoughts yields
            # content="" — which is a failure, not an answer.
            hint = (
                " (the model produced reasoning but no answer: its whole"
                " token budget was likely spent thinking — raise max_tokens)"
                if str(message.get("reasoning", "")).strip()
                else " (raise max_tokens, or try another model)"
            )
            raise RuntimeError("the model returned an empty answer" + hint)
        return content
