"""HTTP client for CORDIS — EU public research-results open data (no credentials).

CORDIS is public open data (CC BY), so unlike the OPS client there is no OAuth:
the client just fetches a result payload over the injected ``HttpTransport`` and
maps status codes to typed errors (404 -> skip; other 4xx/5xx -> error). Endpoint
and throttle live in config (rule 3); nothing here is a secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ...config import ConnectorsConfig
from ..base import RawRecord
from ..http import HttpTransport, UrllibTransport


class CordisError(Exception):
    """A CORDIS fetch failed (non-404 HTTP status)."""


class CordisNotFound(CordisError):
    """The requested CORDIS result does not exist (404) — skip this ref."""


@dataclass
class CordisSettings:
    base_url: str
    source_layer: str = "L1.cordis"
    request_timeout_seconds: float = 30.0
    projects_base_url: str | None = None  # for Layer-0 graph population (T10)

    @classmethod
    def from_config(cls, config: ConnectorsConfig) -> "CordisSettings":
        section = config.section("cordis")
        if not section.get("base_url"):
            raise ValueError("cordis connector config missing 'base_url'")
        projects = section.get("projects_base_url")
        return cls(
            base_url=str(section["base_url"]).rstrip("/"),
            source_layer=section.get("source_layer", "L1.cordis"),
            request_timeout_seconds=float(section.get("request_timeout_seconds", 30.0)),
            projects_base_url=str(projects).rstrip("/") if projects else None,
        )


class CordisClient:
    """Fetch a CORDIS result record by id or URL over an HttpTransport."""

    def __init__(self, settings: CordisSettings, *, transport: HttpTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport or UrllibTransport()

    def _url(self, ref: str, base: str) -> str:
        if ref.startswith(("http://", "https://")):
            return ref
        return f"{base}/{ref}"

    def _fetch(self, ref: str, base: str, what: str) -> RawRecord:
        url = self._url(ref, base)
        resp = self._transport.request(
            "GET",
            url,
            headers={"Accept": "application/json"},
            timeout=self.settings.request_timeout_seconds,
        )
        if resp.status == 404:
            raise CordisNotFound(f"CORDIS {what} not found: {ref}")
        if resp.status >= 400:
            raise CordisError(f"CORDIS returned HTTP {resp.status} for {ref}")
        return RawRecord(
            ref=ref,
            locator=url,
            payload=resp.body,
            content_type=resp.header("Content-Type", "application/json") or "application/json",
            retrieved_at=datetime.now(timezone.utc),
        )

    def fetch_result(self, ref: str) -> RawRecord:
        return self._fetch(ref, self.settings.base_url, "result")

    def fetch_project(self, ref: str) -> RawRecord:
        """Fetch a CORDIS project (its participating organisations drive Layer-0)."""
        base = self.settings.projects_base_url or self.settings.base_url
        return self._fetch(ref, base, "project")
