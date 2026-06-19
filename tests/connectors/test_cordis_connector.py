"""CordisConnector end-to-end (E10): normalise + ground + persist, idempotent."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from forge.config import (
    load_dormancy_config,
    load_governance_config,
    load_organisation_config,
)
from forge.connectors.cordis import CordisClient, CordisConnector, CordisSettings
from forge.connectors.http import HttpResponse
from forge.db.models import AssetType
from forge.dormancy import assess_asset
from forge.repository import get_asset, provenance_map

from .fakes import FakeTransport

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _json_response(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {"Content-Type": "application/json"}, (FIXTURES / name).read_bytes())


def _connector(transport) -> CordisConnector:
    settings = CordisSettings(base_url="https://cordis.test/api")
    return CordisConnector(CordisClient(settings, transport=transport))


def test_run_normalises_grounds_and_persists(session):
    gov = load_governance_config("config/governance.yaml")
    transport = FakeTransport([(("GET", "464190"), _json_response("cordis_result_single.json"))])

    report = _connector(transport).run(["464190"], session, policy=gov)
    assert report.ok and len(report.saved) == 1, report.failed

    asset = get_asset(session, report.saved[0])
    assert asset.asset_type is AssetType.project_result
    assert asset.title.startswith("Photonic neuromorphic")
    assert asset.owners == ["SYNTHETIC RESEARCH ORG", "SYNTHETIC UNIVERSITY"]
    assert asset.key_dates["end_date"] == "2022-09-30"
    assert asset.source_layer == "L1.cordis"

    # Grounding (rule 1): every populated factual field is sourced to CORDIS,
    # under the public licence (rule 5 — public open data, never licensed raw).
    pmap = provenance_map(asset)
    for field in asset.populated_groundable_fields():
        assert field in pmap and pmap[field], field
    src = pmap["title"][0]
    assert src.licence.value == "public"
    assert src.locator == "https://cordis.europa.eu/result/rcn/464190_en.html"


def test_ingested_project_result_is_dormancy_assessable(session):
    transport = FakeTransport([(("GET", "464190"), _json_response("cordis_result_single.json"))])
    report = _connector(transport).run(["464190"], session)
    asset = get_asset(session, report.saved[0])

    # The project_result ruleset runs end-to-end on the ingested asset (E10 closes
    # the loop: a concluded EU project that ended in-window is a dormancy candidate).
    verdict = assess_asset(
        asset,
        load_dormancy_config("config/dormancy.yaml"),
        as_of=date(2025, 1, 1),
        org=load_organisation_config("config/organisation.yaml"),
    )
    assert verdict.ruleset == "project_results"
    assert any(c.name == "ended_in_window" for c in verdict.conditions)


def test_empty_result_is_skipped_not_persisted(session):
    transport = FakeTransport([(("GET", "multi"), _json_response("cordis_results_multi.json"))])
    report = _connector(transport).run(["multi"], session)
    # Two objects in the payload, but the content-less one is dropped (rule 7).
    assert len(report.saved) == 1
    asset = get_asset(session, report.saved[0])
    assert asset.title.startswith("Solid-state battery")


def test_rerun_is_idempotent(session):
    transport = FakeTransport([(("GET", "464190"), _json_response("cordis_result_single.json"))])
    connector = _connector(transport)

    first = connector.run(["464190"], session)
    assert len(first.saved) == 1

    second = connector.run(["464190"], session)
    assert second.saved == [] and len(second.skipped) == 1  # deduped by locator
