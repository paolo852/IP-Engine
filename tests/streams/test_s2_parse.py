"""Parsing OPS published-data search XML."""

from __future__ import annotations

from pathlib import Path

from forge.streams.s2_patents import parse_search

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
