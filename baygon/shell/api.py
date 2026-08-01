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

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from baygon.core.errors import BaygonError, UnknownIntentError, ValidationRequiredError
from baygon.core.kernel import Kernel

MAX_BODY_BYTES = 64 * 1024


class BaygonAPIHandler(BaseHTTPRequestHandler):
    kernel: Kernel  # set by make_server on the handler subclass

    server_version = "BaygonAPI"

    # ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if self.path == "/health":
            self._json(200, {"status": "ok", "ready": self.kernel.ready,
                             "project": self.kernel.config.project_name})
        elif self.path == "/capabilities":
            self._json(200, self.kernel.capabilities())
        elif self.path == "/context":
            self._json(200, self.kernel.context())
        elif self.path == "/history":
            self._json(200, self.kernel.history())
        else:
            self._json(404, {"error": f"unknown path {self.path!r}"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/plan", "/run"):
            self._json(404, {"error": f"unknown path {self.path!r}"})
            return
        try:
            body = self._read_body()
            intent = body["intent"]
        except (KeyError, TypeError, ValueError) as exc:
            self._json(400, {"error": f"invalid request body: {exc}"})
            return

        try:
            if self.path == "/plan":
                plan = self.kernel.plan(str(intent), source="api")
                self._json(200, {"plan": plan.to_dict(), "explanation": plan.explain()})
            else:
                plan = self.kernel.plan(str(intent), source="api")
                approved = bool(body.get("approved", False))
                result = self.kernel.execute(plan, approved=approved)
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
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        # The API stays quiet; observability goes through the event bus.
        return


def make_server(kernel: Kernel, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    handler = type("BoundBaygonAPIHandler", (BaygonAPIHandler,), {"kernel": kernel})
    return ThreadingHTTPServer((host, port), handler)


def serve(kernel: Kernel, host: str = "127.0.0.1", port: int = 8787) -> None:
    server = make_server(kernel, host, port)
    print(f"baygon api listening on http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
