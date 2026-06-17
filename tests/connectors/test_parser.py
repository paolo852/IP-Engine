"""OPS biblio XML parsing, including missing-field edge cases."""

from __future__ import annotations

from forge.connectors.epo_ops.parser import parse_biblio

from .fakes import load_fixture


def test_parses_full_document():
    (p,) = parse_biblio(load_fixture("ops_biblio_single.xml"))

    assert p.publication_id == "EP9999999A1"
    assert p.country == "EP" and p.kind == "A1"
    # English title preferred over the German one.
    assert p.title == "Synthetic photonic interconnect for edge AI"
    assert p.abstract.startswith("A synthetic photonic interconnect")
    # epodoc data-format chosen for parties (deduped, no GMBH suffix variant).
    assert p.applicants == ["SYNTHETIC RESEARCH ORG"]
    assert p.inventors == ["ROSSI ALESSANDRO", "BIANCHI BEATRICE"]
    assert p.publication_date == "2021-01-06"
    assert p.application_date == "2019-07-01"
    assert p.priority_date == "2018-07-04"
    assert p.ipc_classes and p.ipc_classes[0].startswith("G02B")


def test_parses_minimal_document_without_raising():
    (p,) = parse_biblio(load_fixture("ops_biblio_minimal.xml"))

    assert p.publication_id == "EP8888888A1"
    # No English title -> falls back to the only (French) one.
    assert p.title == "Dispositif synthétique de mesure"
    assert p.abstract is None
    assert p.inventors == []
    assert p.applicants == ["SYNTHETIC UNIVERSITY"]
    assert p.priority_date is None
    assert p.application_date == "2018-08-10"


def test_parses_multiple_documents_in_one_response():
    patents = parse_biblio(load_fixture("ops_biblio_multi.xml"))
    assert [p.publication_id for p in patents] == ["EP7777777A1", "EP7777778B1"]


def test_blank_payload_yields_no_patents_when_no_documents():
    payload = (
        b'<ops:world-patent-data xmlns:ops="http://ops.epo.org">'
        b"<exchange-documents/></ops:world-patent-data>"
    )
    assert parse_biblio(payload) == []
