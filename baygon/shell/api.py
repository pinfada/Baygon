"""Baygon Shell — REST API interface.

A second interface over the same kernel as the terminal (EF-004): any
device with HTTP — a phone, a tablet, an automation — can express an
intention. Like every interface, it contains no business logic.

Built on the standard library only: no new dependency (EF-019).

Endpoints:

- GET  /health         liveness and readiness
- GET  /capabilities   available capabilities and implementations
- GET  /context        project context (Context Engine)
- GET  /history        executed intentions
- POST /plan           {"intent": "..."} -> plan + explanation
- POST /run            {"intent": "...", "approved": bool} -> execution result

Sensitive plans follow the same rule as the terminal: without
"approved": true the plan is suspended and 428 is returned. Baygon
proposes, the user decides.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.parse
from collections import OrderedDict, deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from baygon.core.errors import BaygonError, UnknownIntentError, ValidationRequiredError
from baygon.core.kernel import Kernel

MAX_BODY_BYTES = 64 * 1024

#: Environment variable holding the API token by default.
TOKEN_ENV_VAR = "BAYGON_API_TOKEN"
#: Secret name looked up in the secrets capability as a fallback.
TOKEN_SECRET_NAME = "API_TOKEN"


def resolve_api_token(kernel: Kernel, env_var: str = TOKEN_ENV_VAR) -> str | None:
    """Resolve the API token without ever reading it from baygon.yaml.

    Order: process environment, then the secrets capability. Secrets are
    never stored in clear text in the configuration (EF-011).
    """
    value = os.environ.get(env_var)
    if value:
        return value
    try:
        secrets = kernel.registry.resolve("secrets")
        return str(secrets.get(TOKEN_SECRET_NAME))
    except Exception:
        return None


#: Length of the throttling window, in seconds.
WINDOW_SECONDS = 60
#: Upper bound on the number of clients tracked at once. Reached only
#: when more distinct addresses than this knock within a single window.
DEFAULT_MAX_CLIENTS = 10_000


class RateLimiter:
    """Sliding-window throttle per client (ENF-011: abuse stays isolated).

    Memory is bounded on both sides: windows that have gone quiet are
    swept once per window, and the number of tracked clients never
    exceeds ``max_clients`` — a flood of forged source addresses cannot
    grow the server's memory without end. Clients are held in
    least-recently-seen order, so the one still knocking is the last
    that would ever be dropped.
    """

    def __init__(
        self,
        per_minute: int,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_minute = per_minute
        self.max_clients = max_clients
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_sweep = clock()
        self._lock = threading.Lock()

    def tracked_clients(self) -> list[str]:
        """Clients currently held in memory (least recently seen first)."""
        with self._lock:
            return list(self._hits)

    def allow(self, client: str) -> bool:
        now = self._clock()
        with self._lock:
            self._forget_quiet_clients(now)
            hits = self._hits.get(client)
            if hits is None:
                hits = self._hits[client] = deque()
            # Seeing a client refreshes its position: eviction always
            # starts with whoever has been quiet the longest.
            self._hits.move_to_end(client)
            while hits and now - hits[0] > WINDOW_SECONDS:
                hits.popleft()
            allowed = len(hits) < self.per_minute
            if allowed:
                hits.append(now)
            self._enforce_cap()
            return allowed

    def _forget_quiet_clients(self, now: float) -> None:
        """Drop windows that have left the minute. Swept once per window."""
        if now - self._last_sweep < WINDOW_SECONDS:
            return
        self._last_sweep = now
        # A window whose last hit has left the minute says nothing about
        # the present: dropping it loses no throttling state.
        stale = [
            name for name, hits in self._hits.items()
            if not hits or now - hits[-1] > WINDOW_SECONDS
        ]
        for name in stale:
            del self._hits[name]

    def _enforce_cap(self) -> None:
        """Last-resort bound when more clients than the cap are all active.

        Entries go least-recently-seen first, so the client currently
        being served — and any client still knocking — is never the one
        dropped.
        """
        while len(self._hits) > self.max_clients:
            self._hits.popitem(last=False)


class BaygonAPIHandler(BaseHTTPRequestHandler):
    #: Project router (one or several projects), set by make_server.
    target: Any
    token: str | None = None
    limiter: RateLimiter | None = None

    server_version = "BaygonAPI"

    # ------------------------------------------------------------------

    @property
    def kernel(self) -> Kernel:
        """Kernel of the project addressed by this request."""
        return self.target.resolve(self._intent_text, explicit=self._project)

    def _route(self, intent_text: str = "", project: str | None = None) -> Kernel:
        self._intent_text = intent_text
        self._project = project
        return self.kernel

    def _query_project(self) -> str | None:
        query = urllib.parse.urlsplit(self.path).query
        values = urllib.parse.parse_qs(query).get("project")
        return values[0] if values else None

    def _authorized(self) -> bool:
        if self.token is None:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[len("Bearer "):], self.token)

    def _require_auth(self) -> bool:
        """Return True when the request may proceed; reply 401 otherwise."""
        if self._authorized():
            return True
        # Every authentication failure is auditable (ENF-009): publish on
        # every project's bus, since we cannot know the intended target.
        for name in self.target.projects():
            self.target.kernel(name).bus.publish(
                "AuthFailed", client=self.client_address[0], path=self.path
            )
        self._json(401, {"error": "authentication required: send 'Authorization: Bearer <token>'"})
        return False

    def _throttled(self) -> bool:
        """Reply 429 and return True when the client exceeded the limit."""
        if self.limiter is None or self.path == "/health":
            return False
        if self.limiter.allow(self.client_address[0]):
            return False
        self.send_response(429)
        data = json.dumps({"error": "too many requests"}).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Retry-After", "60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if self._throttled():
            return
        if self.path in ("/", "/ui"):
            # Static shell page: no project data, no business logic —
            # every data call it makes goes through the token-gated API.
            from baygon.shell.web import PAGE

            data = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            # The page ships with the server: a cached copy is an older
            # Baygon's interface talking to a newer one. Upgrading the
            # server must be enough to upgrade what the operator runs.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/health":
            # Liveness stays open: it exposes no project data beyond names.
            names = self.target.projects()
            health = {
                "status": "ok",
                "projects": names,
                "ready": all(self.target.kernel(name).ready for name in names),
            }
            if len(names) == 1:
                health["project"] = names[0]
            self._json(200, health)
        elif not self._require_auth():
            return
        elif self.path.split("?")[0] == "/projects":
            self._json(200, self.target.projects())
        elif self.path.split("?")[0] == "/doctor" and self._query_project() is None:
            # Without a project named, answer for every one of them:
            # the overview is the whole point of asking here.
            self._json(200, self.target.readiness())
        elif self.path.split("?")[0] in (
            "/capabilities", "/models", "/context", "/history", "/doctor"
        ):
            try:
                kernel = self._route(project=self._query_project())
            except BaygonError as exc:
                self._json(400, {"error": str(exc)})
                return
            reader = {
                "/capabilities": kernel.capabilities,
                "/models": kernel.models,
                "/context": kernel.context,
                "/history": kernel.history,
                "/doctor": kernel.readiness,
            }[self.path.split("?")[0]]
            self._json(200, reader())
        else:
            self._json(404, {"error": f"unknown path {self.path!r}"})

    def do_POST(self) -> None:  # noqa: N802
        if self._throttled():
            return
        if not self._require_auth():
            return
        if self.path.split("?")[0] == "/reload":
            try:
                kernel = self._route(project=self._query_project())
                kernel.reload()
                self._json(200, {"reloaded": True, "capabilities": kernel.capabilities()})
            except BaygonError as exc:
                self._json(409, {"reloaded": False, "error": str(exc)})
            return
        if self.path not in ("/plan", "/run"):
            self._json(404, {"error": f"unknown path {self.path!r}"})
            return
        try:
            body = self._read_body()
            intent = body["intent"]
        except (KeyError, TypeError, ValueError) as exc:
            self._json(400, {"error": f"invalid request body: {exc}"})
            return

        # Session options: target project, AI mode and chosen model.
        session = {"ai": bool(body.get("ai", True)), "ai_model": body.get("model")}
        try:
            kernel = self._route(str(intent), project=body.get("project"))
        except BaygonError as exc:
            self._json(400, {"error": str(exc)})
            return
        try:
            if self.path == "/plan":
                plan = kernel.plan(str(intent), source="api", **session)
                self._json(200, {"plan": plan.to_dict(), "explanation": plan.explain()})
            else:
                plan = kernel.plan(str(intent), source="api", **session)
                approved = bool(body.get("approved", False))
                result = kernel.execute(plan, approved=approved)
                self._json(200 if result.success else 502, result.to_dict())
        except UnknownIntentError as exc:
            self._json(400, {"error": str(exc), "supported": exc.supported})
        except ValidationRequiredError as exc:
            self._json(428, {
                "error": str(exc),
                "plan": plan.to_dict(),
                "hint": "re-send with \"approved\": true to validate this plan",
            })
        except BaygonError as exc:
            self._json(500, {"error": str(exc)})

    # ------------------------------------------------------------------

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            raise ValueError("empty body")
        if length > MAX_BODY_BYTES:
            raise ValueError("body too large")
        parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("body must be a JSON object")
        return parsed

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        # The API stays quiet; observability goes through the event bus.
        return


def make_server(
    target: Any,
    host: str = "127.0.0.1",
    port: int = 8787,
    token: str | None = None,
    rate_limit_per_minute: int | None = None,
) -> ThreadingHTTPServer:
    """`target` is a Kernel (single project) or a ProjectManager."""
    if isinstance(target, Kernel):
        from baygon.core.projects import SingleProject

        target = SingleProject(target)
    limiter = RateLimiter(rate_limit_per_minute) if rate_limit_per_minute else None
    handler = type(
        "BoundBaygonAPIHandler", (BaygonAPIHandler,),
        {"target": target, "token": token, "limiter": limiter},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(
    kernel: Kernel,
    host: str = "127.0.0.1",
    port: int = 8787,
    token: str | None = None,
    rate_limit_per_minute: int | None = 120,
) -> None:
    server = make_server(kernel, host, port, token=token,
                         rate_limit_per_minute=rate_limit_per_minute)
    mode = "authenticated" if token else "UNAUTHENTICATED (--insecure)"
    print(f"baygon api listening on http://{host}:{server.server_address[1]} [{mode}]")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
