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
import socket
import urllib.parse
import urllib.request
from typing import Any

from baygon.capabilities import AICapability

#: How long a model may take to compose its answer. Generous on
#: purpose: a local reasoning model routinely needs a minute or more.
DEFAULT_TIMEOUT_SECONDS = 120.0
#: How long merely *reaching* the endpoint may take. Connecting either
#: succeeds in seconds or never will, so this stays short — it is what
#: an operator away from the machine hosting the model runs into.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
#: Freshness is informative, so its request never waits long.
LIST_TIMEOUT_SECONDS = 15.0


class EndpointUnreachable(RuntimeError):
    """The endpoint could not even be connected to.

    Distinct from every other failure so a caller can tell "out of
    reach" from "answered something unexpected" without reading the
    message — and without probing the endpoint a second time.
    """


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
        parsed = urllib.parse.urlsplit(str(self.config.get("base_url", "")))
        return parsed.hostname or "", parsed.port or (
            443 if parsed.scheme == "https" else 80
        )

    def probes_directly(self) -> bool:
        """Whether connecting straight to the endpoint proves anything.

        Behind a proxy it does not: the endpoint is not who we would be
        talking to, so a direct probe would answer the wrong question
        and refuse a setup that actually works — exactly the networks
        met away from home.
        """
        if self.connect_timeout() <= 0:
            return False
        scheme = urllib.parse.urlsplit(str(self.config.get("base_url", ""))).scheme
        host, _ = self.endpoint()
        if not host:
            return False
        if urllib.request.getproxies().get(scheme) and not urllib.request.proxy_bypass(host):
            return False
        return True

    def require_reachable(self) -> None:
        """Give up on an out-of-reach endpoint in seconds, not minutes.

        `urlopen` applies one budget to connecting *and* answering, so a
        generous response timeout also means a generous wait for an
        endpoint that will never reply.
        """
        if not self.probes_directly():
            return
        host, port = self.endpoint()
        seconds = self.connect_timeout()
        try:
            socket.create_connection((host, port), timeout=seconds).close()
        except OSError as exc:
            raise EndpointUnreachable(
                f"AI endpoint {host}:{port} is unreachable after {seconds:g}s ({exc}); "
                "choose another declared model for this session, or run without AI"
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
