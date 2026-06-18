"""S1 funding stream: derived aggregates, licence separation, parsing."""

from __future__ import annotations

from pathlib import Path

from forge.streams.s1_funding import (
    FundingSearch,
    S1FundingStream,
    parse_funding,
)

from .fakes import profile

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CONFIG = {"funding_window_years": 3, "max_investors": 5}


class FakeS1Client:
    def __init__(self, search: FundingSearch):
        self._search = search
        self.calls: list[tuple] = []

    def search_funding(self, query, *, years):
        self.calls.append((query, tuple(years)))
        return self._search


def search(**over) -> FundingSearch:
    base = dict(
        total_amount_eur=45_000_000.0,
        round_count=8,
        investors=["VC One", "VC Two", "Growth Fund"],
    )
    base.update(over)
    return FundingSearch(**base)


def stream(client) -> S1FundingStream:
    return S1FundingStream(client, config=CONFIG)


def test_funding_momentum_and_investors_are_emitted():
    client = FakeS1Client(search())
    result = stream(client).run(
        profile(["optical interconnect", "edge inference"]), as_of_year=2023
    )

    fm = result.signal("funding_momentum")
    assert fm.value == 45_000_000.0
    assert "€45.0M" in fm.detail
    inv = result.signal("notable_investors")
    assert inv.value == 3.0 and "VC One" in inv.detail
    # window of 3 years ending 2023
    assert client.calls[0][1] == (2021, 2022, 2023)


def test_evidence_is_licensed_and_derived_only():
    result = stream(FakeS1Client(search())).run(profile(["optical interconnect"]), as_of_year=2023)
    evidence = result.evidence()
    # Every S1 evidence record is licensed-dealroom and points at an AGGREGATE
    # locator (a query pointer), never a raw per-company/round record.
    assert evidence
    for e in evidence:
        assert e.source.licence.value == "licensed_dealroom"
        assert e.source.locator.startswith("dealroom:funding:") or e.source.locator.startswith(
            "dealroom:investors:"
        )
    # No company name from the raw rounds leaks into an evidence locator.
    assert not any("Acme" in e.source.locator for e in evidence)


def test_no_query_terms_yields_no_signals():
    assert stream(FakeS1Client(search())).run(profile([])).sub_signals == []


def test_no_investors_skips_that_signal():
    result = stream(FakeS1Client(search(investors=[]))).run(
        profile(["x"]), as_of_year=2023
    )
    assert result.signal("funding_momentum") is not None
    assert result.signal("notable_investors") is None


def test_parse_funding_aggregates_and_dedupes_investors():
    parsed = parse_funding((FIXTURES / "dealroom_funding.json").read_bytes())
    assert parsed.total_amount_eur == 45_000_000.0
    assert parsed.round_count == 8
    # Investors de-duplicated across rounds, order preserved.
    assert parsed.investors == ["VC One", "VC Two", "Growth Fund", "Sovereign Tech Fund"]
    # Raw rounds are available in memory (for aggregation) but the stream never
    # turns them into evidence.
    assert len(parsed.rounds) == 3
