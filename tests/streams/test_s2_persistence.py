"""Persisting S2 evidence and reading it back, with provenance intact."""

from __future__ import annotations

from forge.streams.s2_patents import (
    CitingDoc,
    S2PatentsStream,
    SearchHit,
    SearchResult,
    YearCount,
)
from forge.repository import get_evidence, save_asset, save_stream_result

from ..synthetic.assets import synthetic_patent_bundle
from .fakes import FakeS2Client, profile


def test_stream_evidence_round_trips(session):
    asset = save_asset(session, synthetic_patent_bundle())

    client = FakeS2Client(
        search=SearchResult(total=12, hits=[SearchHit("EP111A1", "Neighbour", 0.6)]),
        year_counts=[YearCount(2022, 4), YearCount(2023, 6)],
        citing=[CitingDoc("EP999A1", entity="Acme Corp")],
    )
    result = S2PatentsStream(client, config={"filing_window_years": 2, "max_neighbours": 5}).run(
        profile(["optical interconnect"]), publication_id="EP9999999A1", as_of_year=2023
    )

    saved = save_stream_result(session, asset, result)
    assert len(saved) == 3  # 1 neighbour + 1 trend + 1 citation
    session.expunge_all()

    rows = get_evidence(session, asset.id, stream="S2_patents")
    assert len(rows) == 3
    assert all(r.source.licence.value == "free" for r in rows)
    assert all(r.source.source_type == "epo_ops" for r in rows)
    assert any("cites EP9999999A1" in r.snippet for r in rows)
    # The check constraint held: every match_strength is in [0, 1].
    assert all(0.0 <= r.match_strength <= 1.0 for r in rows)
