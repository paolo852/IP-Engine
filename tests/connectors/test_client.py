"""OPS client: auth flow, token caching, throttling, and HTTP error mapping."""

from __future__ import annotations

import pytest

from forge.connectors.epo_ops import (
    OpsAuthError,
    OpsNotFound,
    OpsThrottled,
)
from forge.connectors.epo_ops.client import OpsClient
from forge.connectors.http import HttpResponse

from .fakes import FakeTransport, make_client, make_settings, token_response, xml_response

AUTH = ("POST", "auth/accesstoken")


def test_fetch_returns_raw_record():
    transport = FakeTransport(
        [
            (AUTH, token_response()),
            (("GET", "epodoc/EP9999999/biblio"), xml_response("ops_biblio_single.xml")),
        ]
    )
    client = make_client(transport)

    raw = client.fetch_biblio("EP9999999")
    assert raw.ref == "EP9999999"
    assert "epodoc/EP9999999/biblio" in raw.locator
    assert b"Synthetic photonic interconnect" in raw.payload
    assert raw.retrieved_at is not None


def test_token_is_cached_across_fetches():
    transport = FakeTransport(
        [(AUTH, token_response()), (("GET", "/biblio"), xml_response("ops_biblio_single.xml"))]
    )
    client = make_client(transport)

    client.fetch_biblio("EP9999999")
    client.fetch_biblio("EP9999999")

    auth_calls = [c for c in transport.calls if c[0] == "POST"]
    assert len(auth_calls) == 1  # authenticated once, reused the token


def test_missing_credentials_raise_auth_error():
    transport = FakeTransport([(AUTH, token_response())])
    client = OpsClient(make_settings(), key=None, secret=None, transport=transport)
    with pytest.raises(OpsAuthError, match="missing OPS credentials"):
        client.fetch_biblio("EP9999999")


def test_auth_http_failure_raises():
    transport = FakeTransport([(AUTH, HttpResponse(401, {}, b"bad creds"))])
    client = make_client(transport)
    with pytest.raises(OpsAuthError, match="auth failed"):
        client.fetch_biblio("EP9999999")


def test_404_maps_to_not_found():
    transport = FakeTransport(
        [(AUTH, token_response()), (("GET", "/biblio"), HttpResponse(404, {}, b""))]
    )
    with pytest.raises(OpsNotFound):
        make_client(transport).fetch_biblio("EP0000000")


def test_403_quota_maps_to_throttled():
    resp = HttpResponse(403, {"X-Rejection-Reason": "IndividualQuotaPerHour"}, b"")
    transport = FakeTransport([(AUTH, token_response()), (("GET", "/biblio"), resp)])
    with pytest.raises(OpsThrottled, match="IndividualQuotaPerHour"):
        make_client(transport).fetch_biblio("EP1111111")


def test_401_on_fetch_triggers_reauth_and_retry():
    # First GET rejected (stale token), then a fresh token works.
    seq = iter(
        [HttpResponse(401, {}, b""), xml_response("ops_biblio_single.xml")]
    )
    transport = FakeTransport(
        [(AUTH, token_response()), (("GET", "/biblio"), lambda: next(seq))]
    )
    client = make_client(transport)

    raw = client.fetch_biblio("EP9999999")
    assert b"Synthetic photonic" in raw.payload
    assert len([c for c in transport.calls if c[0] == "POST"]) == 2  # re-authed once


def test_throttle_sleeps_to_respect_min_interval():
    slept: list[float] = []
    client = make_client(FakeTransport([]), min_request_interval_seconds=2.0)
    client._clock = lambda: 100.0
    client._sleep = slept.append
    client._last_request_at = 99.5  # last call was 0.5s ago -> owe 1.5s

    client._throttle()
    assert slept and abs(slept[0] - 1.5) < 1e-9


def test_throttle_does_not_sleep_on_first_call():
    slept: list[float] = []
    client = make_client(FakeTransport([]), min_request_interval_seconds=2.0)
    client._sleep = slept.append
    client._throttle()
    assert slept == []
