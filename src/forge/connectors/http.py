"""Tiny HTTP transport abstraction.

Connectors talk to the network only through an ``HttpTransport``. The default is
urllib (no third-party dependency); tests inject a fake so the suite never makes
a live call. 4xx/5xx responses are returned (not raised) so connectors can treat
status codes as data (e.g. 404 -> skip, 403 -> throttled).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str, default: str | None = None) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default


class HttpError(Exception):
    """Transport-level failure (DNS, connection, timeout) — not an HTTP status."""


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class UrllibTransport:
    """Default transport backed by the standard library."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        req = urllib.request.Request(
            url, data=data, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(
                    status=resp.status,
                    headers={k: v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            # An HTTP status response (4xx/5xx) is data, not an error, for us.
            return HttpResponse(
                status=exc.code,
                headers={k: v for k, v in (exc.headers or {}).items()},
                body=exc.read(),
            )
        except urllib.error.URLError as exc:  # pragma: no cover - network dependent
            raise HttpError(f"network error for {url}: {exc.reason}") from exc
