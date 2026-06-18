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


_PATENT_DOC = (
    "United States Patent\n"
    "(54) Title of Invention: Solid-state lithium battery with sulfide electrolyte\n"
    "(57) Abstract\n"
    "A solid-state lithium battery reduces dendrite formation at high current density.\n\n"
    "What is claimed is:\n"
    "1. A battery cell comprising a sulfide glass electrolyte and a lithium additive.\n"
).encode("utf-8")

_RESULT_DOC = (
    "Deliverable D3.2 — Work Package 3\n"
    "A scalable enzymatic process for depolymerising mixed plastic waste\n\n"
    "Abstract\n"
    "This paper presents an enzymatic process for depolymerising plastic waste.\n\n"
    "References\n[1] doi:10.1000/example.2021\n"
).encode("utf-8")


def test_upload_patent_classifies_and_scores(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    r = client.post(
        "/upload",
        files={"file": ("patent.txt", _PATENT_DOC, "text/plain")},
        data={"licence": "public"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/asset/")
    detail = client.get(loc).text
    assert "patent" in detail.lower()
    assert "Ventureability" in detail
    assert "Classified as patent" in detail            # explainable classification note


def test_upload_result_classified_as_unpatented(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    r = client.post(
        "/upload",
        files={"file": ("deliverable.txt", _RESULT_DOC, "text/plain")},
        data={"licence": "public"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = client.get(r.headers["location"]).text
    assert "project_result" in detail            # asset type from classification
    assert "Classified as unpatented result" in detail


def test_upload_unreadable_document_bounces(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    r = client.post(
        "/upload",
        files={"file": ("empty.txt", b"   ", "text/plain")},
        data={"licence": "public"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/upload?error=")


def test_viewer_cannot_upload(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "viewer")
    assert client.get("/upload").status_code == 403
    r = client.post(
        "/upload",
        files={"file": ("patent.txt", _PATENT_DOC, "text/plain")},
        data={"licence": "public"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_ingest_epo_form_renders(client, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    monkeypatch.delenv("FORGE_EPO_OPS_KEY", raising=False)
    r = client.get("/ingest-epo")
    assert r.status_code == 200
    assert "Ingest a patent from EPO" in r.text
    assert "not configured" in r.text  # no key -> the warning shows


def test_ingest_epo_without_key_reports_error(client, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    monkeypatch.delenv("FORGE_EPO_OPS_KEY", raising=False)
    r = client.post("/ingest-epo", data={"refs": "EP1000000"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ingest-epo?error=")
    assert "FORGE_EPO_OPS_KEY" in r.headers["location"]


def test_ingest_epo_empty_input_reports_error(client, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    r = client.post("/ingest-epo", data={"refs": "   "}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ingest-epo?error=")


def test_viewer_cannot_ingest_epo(client, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "viewer")
    assert client.get("/ingest-epo").status_code == 403
    assert client.post(
        "/ingest-epo", data={"refs": "EP1000000"}, follow_redirects=False
    ).status_code == 403


def _ventureability(value, coverage):
    from forge.scoring import DimensionScore, VentureabilityScore

    dims = [DimensionScore("technology_maturity", value, "rationale")]
    return VentureabilityScore(value, coverage, dims, {"technology_maturity": 1.0})


def test_low_coverage_asset_flagged_for_human_review(client, session):
    from forge.repository import save_asset, save_score

    from .synthetic.assets import synthetic_patent_bundle

    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _ventureability(0.6, 0.2), routing="watch")  # below floor
    detail = client.get(f"/asset/{asset.id}").text
    assert "Insufficient market evidence" in detail
    assert "needs human review" in detail
    assert "provisional" in detail


def test_well_covered_asset_not_flagged(client, session):
    from forge.repository import save_asset, save_score

    from .synthetic.assets import synthetic_patent_bundle

    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _ventureability(0.7, 0.85), routing="sprint")  # above floor
    detail = client.get(f"/asset/{asset.id}").text
    assert "Insufficient market evidence" not in detail


def test_raw_profile_is_collapsed_search_basis(client, seeded):
    from forge.db.models import Asset

    asset = seeded.query(Asset).filter(Asset.title.like("Low-power photonic%")).one()
    detail = client.get(f"/asset/{asset.id}").text
    # The paraphrase is demoted to an expandable "search basis", not the headline.
    assert "Search basis" in detail
    assert "<details>" in detail
