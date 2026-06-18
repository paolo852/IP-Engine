"""S1 evidence persists with licensed provenance, derived signals only."""

from __future__ import annotations

from forge.repository import get_evidence, save_asset, save_stream_result
from forge.streams.s1_funding import FundingSearch, S1FundingStream

from ..synthetic.assets import synthetic_patent_bundle
from .fakes import profile


class _Client:
    def search_funding(self, query, *, years):
        return FundingSearch(
            total_amount_eur=30_000_000.0, round_count=5, investors=["VC One", "VC Two"]
        )


def test_s1_evidence_round_trips_licensed(session):
    asset = save_asset(session, synthetic_patent_bundle())
    result = S1FundingStream(_Client(), config={"funding_window_years": 3, "max_investors": 5}).run(
        profile(["optical interconnect"]), as_of_year=2023
    )

    save_stream_result(session, asset, result)
    session.expunge_all()

    rows = get_evidence(session, asset.id, stream="S1_funding")
    assert rows
    assert all(r.source.source_type == "dealroom" for r in rows)
    assert all(r.source.licence.value == "licensed_dealroom" for r in rows)
    # Derived aggregates only — snippets are summaries, not raw records.
    assert any("total funding" in r.snippet for r in rows)
