"""Test doubles for connector I/O — no network, no credentials, no sleeping."""

from __future__ import annotations

import json
from pathlib import Path

from forge.connectors.epo_ops import EpoOpsConnector, OpsClient, OpsSettings
from forge.connectors.http import HttpResponse

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def make_settings(**over) -> OpsSettings:
    base = dict(
        base_url="http://ops.test/3.2/rest-services",
        auth_url="http://ops.test/auth/accesstoken",
        min_request_interval_seconds=0.0,  # tests never sleep unless they opt in
    )
    base.update(over)
    return OpsSettings(**base)


def make_client(transport, **settings_over) -> OpsClient:
    return OpsClient(
        make_settings(**settings_over), key="key", secret="secret", transport=transport
    )


def make_connector(transport, **settings_over) -> EpoOpsConnector:
    return EpoOpsConnector(make_client(transport, **settings_over))


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def xml_response(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {"Content-Type": "application/xml"}, load_fixture(name))


def token_response(access_token: str = "FAKE-TOKEN", expires_in: int = 1200) -> HttpResponse:
    body = json.dumps(
        {"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in}
    ).encode()
    return HttpResponse(200, {"Content-Type": "application/json"}, body)


class FakeTransport:
    """Routes (method, url-substring) -> HttpResponse (or a zero-arg callable).

    Records every call so tests can assert on auth/throttle behaviour. The first
    matching route wins, so register specific substrings before general ones.
    """

    def __init__(self, routes: list[tuple[tuple[str, str], object]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, *, headers=None, data=None, timeout=30.0) -> HttpResponse:
        self.calls.append((method, url))
        for (m, substr), resp in self.routes:
            if m == method and substr in url:
                return resp() if callable(resp) else resp
        return HttpResponse(404, {}, b"no route for " + url.encode())
