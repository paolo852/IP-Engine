"""T10: Layer-0 graph population from CORDIS projects (public data, offline)."""

from __future__ import annotations

from pathlib import Path

from forge.connectors.cordis import CordisClient, CordisSettings
from forge.connectors.http import HttpResponse
from forge.db.models import RelationshipType
from forge.graph import build_layer0, get_companies, populate_from_cordis_project
from forge.connectors.cordis.parser import parse_project

from tests.connectors.fakes import FakeTransport

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _json(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _client(*routes) -> CordisClient:
    settings = CordisSettings(base_url="https://cordis.test/api", projects_base_url="https://cordis.test/api/projects")
    return CordisClient(settings, transport=FakeTransport(list(routes)))


def test_build_layer0_keeps_only_industrial_partners(session):
    project = parse_project(_json("cordis_project_single.json"))
    report = build_layer0(session, project)
    session.commit()

    # Two PRC companies kept; the university (HES) and research centre (REC) skipped.
    assert report.companies_created == 2
    assert report.relationships_added == 2
    assert report.skipped_non_industrial == 2

    companies = get_companies(session)
    names = {c.name for c in companies}
    assert names == {"Aurora Photonics GmbH", "Borealis Systems S.p.A."}
    for c in companies:
        assert c.relationships[0].type is RelationshipType.collaborative_project
        assert c.relationships[0].source_layer == 0
        assert c.relationships[0].source_ref == "cordis:project:101001234"
        assert c.relationships[0].end_date == "2022-12-31"
    aurora = next(c for c in companies if c.name.startswith("Aurora"))
    assert aurora.size == "sme" and aurora.country == "DE"


def test_same_company_across_projects_merges_and_adds_a_tie(session):
    build_layer0(session, parse_project(_json("cordis_project_single.json")))
    session.commit()
    # PHOTON-NEXT reuses Aurora (same PIC, different spelling "G.m.b.H.").
    report = build_layer0(session, parse_project(_json("cordis_project_overlap.json")))
    session.commit()

    assert report.companies_created == 0 and report.companies_matched == 1
    assert report.relationships_added == 1  # a second, distinct project tie

    companies = get_companies(session)
    assert len(companies) == 2  # still just Aurora + Borealis (no duplicate Aurora)
    aurora = next(c for c in companies if c.name.startswith("Aurora"))
    assert len(aurora.relationships) == 2  # one tie per project


def test_populate_from_cordis_project_is_idempotent(session):
    routes = [(("GET", "101001234"), HttpResponse(200, {}, _json("cordis_project_single.json")))]
    client = _client(*routes)

    first = populate_from_cordis_project(session, client, "101001234")
    second = populate_from_cordis_project(session, client, "101001234")

    assert first.relationships_added == 2
    assert second.companies_created == 0 and second.relationships_added == 0  # deduped
    assert len(get_companies(session)) == 2
