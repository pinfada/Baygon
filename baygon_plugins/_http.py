"""Telling "out of reach" from "slow to answer", for HTTP adapters.

Shared by every adapter that talks to a declared endpoint. Not a
capability implementation and not part of the core.

`urlopen` applies one budget to connecting *and* to answering, so a
generous response timeout is also a generous wait for an endpoint that
will never reply. The two are different questions: answering can
legitimately take a minute, while connecting either works within
seconds or will not work at all. That second case is the one an
operator meets when the Docker stack is down or the machine hosting the
service is out of reach.
"""

from __future__ import annotations

import socket
import urllib.parse
import urllib.request

from baygon.capabilities import ActionableError

#: How long merely reaching an endpoint may take.
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0


class EndpointUnreachable(ActionableError):
    """The endpoint could not even be connected to.

    Distinct from every other failure so a caller can tell "out of
    reach" from "answered something unexpected" without reading the
    message — and without probing the endpoint a second time.
    """


def endpoint_of(base_url: str) -> tuple[str, int]:
    """Host and port a base URL points at, port defaulted by scheme."""
    parsed = urllib.parse.urlsplit(str(base_url))
    return parsed.hostname or "", parsed.port or (
        443 if parsed.scheme == "https" else 80
    )


def probes_directly(base_url: str, connect_timeout: float) -> bool:
    """Whether connecting straight to the endpoint proves anything.

    Behind a proxy it does not: the endpoint is not who we would be
    talking to, so a direct probe would answer the wrong question and
    refuse a setup that actually works.
    """
    if connect_timeout <= 0:
        return False
    parsed = urllib.parse.urlsplit(str(base_url))
    host = parsed.hostname or ""
    if not host:
        return False
    if urllib.request.getproxies().get(parsed.scheme) and not urllib.request.proxy_bypass(host):
        return False
    return True


def require_reachable(kind: str, base_url: str, connect_timeout: float) -> None:
    """Give up on an out-of-reach endpoint in seconds, not minutes.

    `kind` names what is being reached ("metrics", "logs", ...) so the
    operator knows which declared provider to look at.
    """
    if not probes_directly(base_url, connect_timeout):
        return
    host, port = endpoint_of(base_url)
    try:
        socket.create_connection((host, port), timeout=connect_timeout).close()
    except OSError as exc:
        raise EndpointUnreachable(
            f"{kind} endpoint {host}:{port} is unreachable after "
            f"{connect_timeout:g}s ({exc})",
            [
                f"start the service listening on {host}:{port}",
                f"or point options.url elsewhere for the {kind} capability",
                "or declare another provider for it in baygon.yaml",
            ],
        ) from exc
