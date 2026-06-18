"""Demo web UI: dashboard, asset detail (grounded), and RBAC-gated writes."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from forge.db.base import make_session_factory
from forge.repository import latest_decision, latest_outcome
from forge.seed import seed_demo
from forge.web import create_app

AS_OF = date(2026, 6, 18)


@pytest.fixture()
def client(engine):
    factory = make_session_factory(engine)
    app = create_app(session_factory=factory)
    return TestClient(app)


@pytest.fixture()
def seeded(session):
    seed_demo(session, as_of=AS_OF)
    return session


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_empty(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No assets yet" in r.text


def test_dashboard_lists_ranked_assets(client, seeded):
    r = client.get("/")
    assert r.status_code == 200
    # Synthetic demo titles and a routing pill appear.
    assert "photonic interconnect" in r.text.lower()
    assert "Committee dashboard" in r.text


def test_asset_detail_shows_score_grounding_and_provenance(client, seeded):
    from forge.db.models import Asset

    asset = seeded.query(Asset).filter(Asset.title.like("Low-power photonic%")).one()
    r = client.get(f"/asset/{asset.id}")
    assert r.status_code == 200
    assert "Ventureability" in r.text
    assert "technology_maturity" in r.text          # dimension breakdown
    assert "asset.abstract" in r.text or "asset.claims_or_description" in r.text  # grounding
    assert "no source → no claim" in r.text         # provenance section
    assert "Dormancy" in r.text


def test_asset_detail_404_for_unknown(client):
    import uuid

    assert client.get(f"/asset/{uuid.uuid4()}").status_code == 404
    assert client.get("/asset/not-a-uuid").status_code == 404


def test_admin_can_record_decision(client, seeded, monkeypatch):
    from forge.db.models import Asset

    monkeypatch.setenv("FORGE_ROLE", "admin")
    asset = seeded.query(Asset).first()
    r = client.post(
        f"/asset/{asset.id}/decide",
        data={"decision": "sprint", "decided_by": "committee@org"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    seeded.expire_all()
    dec = latest_decision(seeded, asset.id)
    assert dec is not None and dec.decision.value == "sprint"
    # The decision snapshots the engine score that informed it.
    assert dec.engine_score is not None


def test_viewer_cannot_record_decision(client, seeded, monkeypatch):
    from forge.db.models import Asset

    monkeypatch.setenv("FORGE_ROLE", "viewer")
    asset = seeded.query(Asset).first()
    r = client.post(
        f"/asset/{asset.id}/decide",
        data={"decision": "sprint"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    seeded.expire_all()
    assert latest_decision(seeded, asset.id) is None


def test_committee_can_record_outcome(client, seeded, monkeypatch):
    from forge.db.models import Asset

    monkeypatch.setenv("FORGE_ROLE", "committee")
    asset = seeded.query(Asset).first()
    r = client.post(
        f"/asset/{asset.id}/outcome",
        data={"outcome": "licensed", "recorded_by": "ops@org"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    seeded.expire_all()
    out = latest_outcome(seeded, asset.id)
    assert out is not None and out.outcome.value == "licensed"


def test_viewer_detail_hides_decision_form(client, seeded, monkeypatch):
    from forge.db.models import Asset

    monkeypatch.setenv("FORGE_ROLE", "viewer")
    asset = seeded.query(Asset).first()
    r = client.get(f"/asset/{asset.id}")
    assert r.status_code == 200
    assert "may not record decisions" in r.text


_PATENT_FORM = {
    "title": "Solid-state lithium battery with sulfide electrolyte",
    "source_locator": "https://patents.google.com/patent/EP3000000A1",
    "licence": "public",
    "asset_type": "patent",
    "abstract": "A solid-state lithium battery reduces dendrite formation at high "
                "current density. The cell improves cycle life for grid storage.",
    "claims_or_description": "A battery cell comprising a sulfide glass electrolyte "
                            "and a lithium-stabilising additive between cathode and anode.",
    "legal_status": "granted",
    "fee_status": "active",
    "priority_date": "2014-09-10",
    "filing_date": "2015-09-01",
    "grant_date": "2018-11-12",
    "inventors": "M. Rossi, L. Bianchi",
    "owners": "Example Research Institute",
}


def test_add_patent_profiles_scores_and_grounds(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    r = client.post("/new", data=_PATENT_FORM, follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/asset/")

    # The detail page (a fresh session) shows a persisted score with breakdown and
    # grounded provenance — proving the whole add → profile → score path committed.
    detail = client.get(location).text
    assert "Ventureability" in detail
    assert "technology_maturity" in detail            # score breakdown persisted
    assert "patents.google.com/patent/EP3000000A1" in detail  # provenance source
    assert "no source → no claim" in detail


def test_add_asset_appears_on_dashboard(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    client.post("/new", data=_PATENT_FORM, follow_redirects=False)
    home = client.get("/").text
    assert "Solid-state lithium battery" in home


def test_viewer_cannot_add_asset(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "viewer")
    assert client.get("/new").status_code == 403
    assert client.post("/new", data=_PATENT_FORM,
                       follow_redirects=False).status_code == 403


def test_add_asset_rejects_restricted_licence(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    bad = {**_PATENT_FORM, "licence": "licensed_dealroom"}
    r = client.post("/new", data=bad, follow_redirects=False)
    # Governance (rule 4) bounces it back to the form with an error, nothing stored.
    assert r.status_code == 303 and r.headers["location"].startswith("/new?error=")
    assert "Solid-state lithium battery" not in client.get("/").text
