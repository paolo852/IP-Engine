"""Parsing OPS published-data search XML."""

from __future__ import annotations

from pathlib import Path

from forge.streams.s2_patents import parse_citing, parse_search

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_search_reads_total_and_hits():
    result = parse_search((FIXTURES / "ops_search.xml").read_bytes())
    assert result.total == 3  # total-result-count, not the sampled page size
    assert [h.publication_id for h in result.hits] == ["EP1234567A1", "EP7654321B1"]


def test_parse_search_handles_empty_result():
    payload = (
        b'<ops:world-patent-data xmlns:ops="http://ops.epo.org">'
        b'<ops:biblio-search total-result-count="0"><ops:search-result/>'
        b"</ops:biblio-search></ops:world-patent-data>"
    )
    result = parse_search(payload)
    assert result.total == 0 and result.hits == []


def test_parse_citing_reads_publication_and_applicant():
    citing = parse_citing((FIXTURES / "ops_citing.xml").read_bytes())
    assert [(c.publication_id, c.entity) for c in citing] == [
        ("EP9990001A1", "ACME PHOTONICS GMBH"),
        ("EP9990002B1", "STANFORD UNIVERSITY"),
    ]


def test_parse_citing_falls_back_to_references_without_biblio():
    # A plain search response (no exchange-document) yields ids without applicants.
    citing = parse_citing((FIXTURES / "ops_search.xml").read_bytes())
    assert [c.publication_id for c in citing] == ["EP1234567A1", "EP7654321B1"]
    assert all(c.entity is None for c in citing)
