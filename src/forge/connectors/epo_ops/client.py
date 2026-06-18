"""OPS REST client: OAuth2 client-credentials auth + bibliographic fetch.

Credentials are read from the environment (FORGE_EPO_OPS_KEY / _SECRET) and never
logged or stored. The token is cached until shortly before expiry. HTTP status
codes are mapped to typed errors so the connector framework can react (404 ->
skip a record, 403 quota -> throttled).
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

from ...config import ConnectorsConfig
from ..base import RawRecord
from ..http import HttpResponse, HttpTransport, UrllibTransport

KEY_ENV = "FORGE_EPO_OPS_KEY"
SECRET_ENV = "FORGE_EPO_OPS_SECRET"

# Refresh the token this many seconds before its stated expiry.
_TOKEN_SKEW_SECONDS = 30


class OpsError(Exception):
    """Base class for OPS client errors."""


class OpsAuthError(OpsError):
    """Authentication failed (bad/missing credentials)."""


class OpsNotFound(OpsError):
    """The requested publication was not found (HTTP 404)."""


class OpsThrottled(OpsError):
    """OPS rejected the call for quota/throttling reasons (HTTP 403/429)."""


@dataclass
class OpsSettings:
    base_url: str
    auth_url: str
    reference_format: str = "epodoc"
    request_timeout_seconds: float = 30.0
    min_request_interval_seconds: float = 1.0
    source_layer: str = "L1.epo_ops"

    @classmethod
    def from_config(cls, config: ConnectorsConfig) -> "OpsSettings":
        section = config.section("epo_ops")
        return cls(
            base_url=section["base_url"].rstrip("/"),
            auth_url=section["auth_url"],
            reference_format=section.get("reference_format", "epodoc"),
            request_timeout_seconds=float(section.get("request_timeout_seconds", 30.0)),
            min_request_interval_seconds=float(
                section.get("min_request_interval_seconds", 1.0)
            ),
            source_layer=section.get("source_layer", "L1.epo_ops"),
        )


class OpsClient:
    def __init__(
        self,
        settings: OpsSettings,
        *,
        key: str | None = None,
        secret: str | None = None,
        transport: HttpTransport | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings
        self._key = key if key is not None else os.environ.get(KEY_ENV)
        self._secret = secret if secret is not None else os.environ.get(SECRET_ENV)
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._sleep = sleep
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._last_request_at: float | None = None

    # -- auth ---------------------------------------------------------------
    def _authenticate(self) -> None:
        if not self._key or not self._secret:
            raise OpsAuthError(
                f"missing OPS credentials: set {KEY_ENV} and {SECRET_ENV}"
            )
        creds = base64.b64encode(f"{self._key}:{self._secret}".encode()).decode()
        resp = self._transport.request(
            "POST",
            self.settings.auth_url,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=b"grant_type=client_credentials",
            timeout=self.settings.request_timeout_seconds,
        )
        if resp.status != 200:
            raise OpsAuthError(f"auth failed: HTTP {resp.status}")
        try:
            payload = json.loads(resp.body)
            token = payload["access_token"]
            expires_in = float(payload.get("expires_in", 1200))
        except (ValueError, KeyError) as exc:
            raise OpsAuthError(f"malformed auth response: {exc}") from exc
        self._token = token
        self._token_expiry = self._clock() + expires_in - _TOKEN_SKEW_SECONDS

    def _ensure_token(self) -> str:
        if self._token is None or self._clock() >= self._token_expiry:
            self._authenticate()
        assert self._token is not None
        return self._token

    # -- throttling ---------------------------------------------------------
    def _throttle(self) -> None:
        interval = self.settings.min_request_interval_seconds
        if interval <= 0 or self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        if elapsed < interval:
            self._sleep(interval - elapsed)

    # -- fetch --------------------------------------------------------------
    def _biblio_url(self, fmt: str, ref: str) -> str:
        quoted = urllib.parse.quote(ref, safe="")
        return f"{self.settings.base_url}/published-data/publication/{fmt}/{quoted}/biblio"

    def biblio_url(self, ref: str) -> str:  # back-compat: configured format
        return self._biblio_url(self.settings.reference_format, ref)

    def reference_candidates(self, ref: str) -> list[tuple[str, str]]:
        """(format, number) variants to try for one input reference.

        OPS is picky about number format — US grants usually want docdb
        (``US.10041971.B2``) while EP works in epodoc — so we parse the input into
        country / number / kind and try the sensible encodings in order, stopping
        at the first that isn't a 404. Unparseable input falls back to the
        configured format verbatim.
        """
        s = ref.strip().upper().replace(" ", "").replace(",", "")
        m = re.match(r"^([A-Z]{2})([0-9]+)([A-Z][0-9]?)?$", s)
        if not m:
            return [(self.settings.reference_format, s)]
        cc, num, kind = m.group(1), m.group(2), m.group(3)
        cands: list[tuple[str, str]] = []
        if kind:
            cands.append(("epodoc", f"{cc}{num}{kind}"))
            cands.append(("docdb", f"{cc}.{num}.{kind}"))
        cands.append(("epodoc", f"{cc}{num}"))
        cands.append(("docdb", f"{cc}.{num}"))
        seen: set[tuple[str, str]] = set()
        return [c for c in cands if not (c in seen or seen.add(c))]

    def _get(self, url: str, token: str) -> HttpResponse:
        self._throttle()
        try:
            return self._transport.request(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/xml"},
                timeout=self.settings.request_timeout_seconds,
            )
        finally:
            self._last_request_at = self._clock()

    def fetch_biblio(self, ref: str) -> RawRecord:
        """Fetch one publication's biblio data as a RawRecord.

        Tries the format variants from ``reference_candidates`` until one resolves
        (a 404 falls through to the next; throttling/other errors propagate).
        Retries once after re-authentication on a 401 (expired/revoked token).
        """
        last_not_found: OpsNotFound | None = None
        for fmt, candidate in self.reference_candidates(ref):
            url = self._biblio_url(fmt, candidate)
            try:
                body, content_type = self.fetch(url, ref=ref)
            except OpsNotFound as exc:
                last_not_found = exc
                continue
            return RawRecord(
                ref=ref,
                locator=url,
                payload=body,
                content_type=content_type,
                retrieved_at=datetime.now(timezone.utc),
            )
        raise last_not_found or OpsNotFound(f"not found: {ref!r}")

    def fetch(self, url: str, *, ref: str = "") -> tuple[bytes, str]:
        """Authenticated GET of an OPS URL → (body, content-type).

        Shared by biblio fetch and the S2 search client. Maps HTTP status to the
        same typed errors and re-authenticates once on a 401.
        """
        what = ref or url
        token = self._ensure_token()
        resp = self._get(url, token)

        if resp.status == 401:  # token rejected — re-auth once and retry
            self._token = None
            resp = self._get(url, self._ensure_token())

        if resp.status == 404:
            raise OpsNotFound(f"not found: {what!r}")
        if resp.status in (403, 429):
            reason = resp.header("X-Rejection-Reason", "")
            raise OpsThrottled(f"OPS throttled {what!r}: HTTP {resp.status} {reason}".strip())
        if resp.status != 200:
            raise OpsError(f"OPS error for {what!r}: HTTP {resp.status}")

        return resp.body, resp.header("Content-Type", "application/xml") or "application/xml"
