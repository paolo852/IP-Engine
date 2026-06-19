"""EpoOpsConnector end-to-end: normalise + ground + persist, with run-loop rules."""

from __future__ import annotations

from forge.connectors.http import HttpResponse
from forge.repository import get_asset, provenance_map

from .fakes import FakeTransport, make_connector, token_response, xml_response

AUTH = ("POST", "auth/accesstoken")


def _routes(biblio_routes):
    return [(AUTH, token_response()), *biblio_routes]


def test_run_normalises_grounds_and_persists(session):
    transport = FakeTransport(
        _routes([(("GET", "epodoc/EP9999999/biblio"), xml_response("ops_biblio_single.xml"))])
    )
    connector = make_connector(transport)

    report = connector.run(["EP9999999"], session)
    assert report.ok and len(report.saved) == 1

    asset = get_asset(session, report.saved[0])
    assert asset.title == "Synthetic photonic interconnect for edge AI"
    assert asset.owners == ["SYNTHETIC RESEARCH ORG"]
    assert asset.inventors == ["ROSSI ALESSANDRO", "BIANCHI BEATRICE"]
    assert asset.key_dates["priority_date"] == "2018-07-04"
    assert asset.source_layer == "L1.epo_ops"
    assert asset.classification_codes and asset.classification_codes[0].startswith("G02B")

    # Grounding: every populated factual field carries OPS provenance (rule 1),
    # and the source is the free/public class (licence separation, rule 5).
    pmap = provenance_map(asset)
    for field in asset.populated_groundable_fields():
        assert field in pmap and pmap[field], field
    src = pmap["title"][0]
    assert src.licence.value == "free"
    assert src.locator == "EP9999999A1"
    assert src.raw_ref == "epodoc:EP9999999A1"  # pointer, not the payload


def test_rerun_is_idempotent(session):
    def fresh_connector():
        transport = FakeTransport(
            _routes([(("GET", "/biblio"), xml_response("ops_biblio_single.xml"))])
        )
        return make_connector(transport)

    first = fresh_connector().run(["EP9999999"], session)
    assert len(first.saved) == 1

    second = fresh_connector().run(["EP9999999"], session)
    assert second.saved == [] and second.skipped == ["EP9999999A1"]


def test_failing_record_does_not_block_the_rest(session):
    transport = FakeTransport(
        _routes(
            [
                (("GET", "epodoc/EP0000000/biblio"), HttpResponse(404, {}, b"")),
                (("GET", "epodoc/EP9999999/biblio"), xml_response("ops_biblio_single.xml")),
            ]
        )
    )
    connector = make_connector(transport)

    report = connector.run(["EP0000000", "EP9999999"], session)
    assert len(report.saved) == 1
    assert len(report.failed) == 1
    assert report.failed[0].ref == "EP0000000"
    assert report.failed[0].stage == "fetch"


def test_one_response_with_multiple_documents_yields_multiple_assets(session):
    transport = FakeTransport(
        _routes([(("GET", "epodoc/EP7777777/biblio"), xml_response("ops_biblio_multi.xml"))])
    )
    connector = make_connector(transport)

    report = connector.run(["EP7777777"], session)
    assert len(report.saved) == 2
    locators = {provenance_map(get_asset(session, aid))["title"][0].locator for aid in report.saved}
    assert locators == {"EP7777777A1", "EP7777778B1"}
