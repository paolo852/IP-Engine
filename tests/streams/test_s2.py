"""S2 stream: query building, sub-signals, and evidence normalisation."""

from __future__ import annotations

from forge.streams.s2_patents import (
    CitingDoc,
    S2PatentsStream,
    SearchHit,
    SearchResult,
    YearCount,
)

from .fakes import FakeS2Client, profile

CONFIG = {"filing_window_years": 5, "max_neighbours": 2}


def make_client(**over) -> FakeS2Client:
    base = dict(
        search=SearchResult(
            total=42,
            hits=[
                SearchHit("EP111A1", "Optical interconnect", 0.9),
                SearchHit("EP222A1", "Photonic switch", 0.8),
                SearchHit("EP333A1", "Waveguide", 0.7),
            ],
        ),
        year_counts=[YearCount(2021, 10), YearCount(2022, 12), YearCount(2023, 14)],
        citing=[CitingDoc("EP999A1", entity="Acme Corp"), CitingDoc("EP998A1")],
    )
    base.update(over)
    return FakeS2Client(**base)


def stream(client) -> S2PatentsStream:
    return S2PatentsStream(client, config=CONFIG)


def test_queries_are_built_from_problem_space_terms():
    qs = stream(make_client()).queries(profile(["optical interconnect", "edge inference"]))
    assert [q.term for q in qs] == ["optical interconnect", "edge inference"]
    assert qs[0].cql == 'txt="optical interconnect"'


def test_run_emits_three_sub_signals_with_expected_values():
    client = make_client()
    result = stream(client).run(
        profile(["optical interconnect", "edge inference"]),
        publication_id="EP9999999A1",
        as_of_year=2023,
    )

    assert result.signal("neighbour_density").value == 42.0
    assert result.signal("filing_trend_slope").value == 2.0  # 10,12,14
    fwd = result.signal("forward_citation_count")
    assert fwd.value == 2.0
    assert "Acme Corp" in fwd.detail

    # The field-level query combined both problem-space terms.
    search_call = next(c for c in client.calls if c[0] == "search")
    assert "optical interconnect" in search_call[1] and "edge inference" in search_call[1]
    # The window asked for 5 years ending 2023.
    fb = next(c for c in client.calls if c[0] == "filings_by_year")
    assert fb[2] == (2019, 2020, 2021, 2022, 2023)


def test_evidence_is_normalised_and_unit_bounded():
    result = stream(make_client()).run(
        profile(["optical interconnect"]), publication_id="EP9999999A1", as_of_year=2023
    )
    evidence = result.evidence()
    # 2 neighbours (capped by max_neighbours) + 1 filing-trend + 2 citations.
    assert len(evidence) == 5
    assert all(0.0 <= e.match_strength <= 1.0 for e in evidence)
    assert all(e.stream == "S2_patents" for e in evidence)
    # Forward-citation evidence is maximally relevant and licensed free.
    citation = next(e for e in evidence if "cites EP9999999A1" in e.snippet)
    assert citation.match_strength == 1.0
    assert citation.source.licence.value == "free"


def test_no_publication_id_skips_forward_citations():
    result = stream(make_client()).run(profile(["optical interconnect"]), as_of_year=2023)
    assert result.signal("forward_citation_count") is None
    assert result.signal("neighbour_density") is not None


def test_no_query_terms_skips_field_signals_but_keeps_citations():
    result = stream(make_client()).run(
        profile([]), publication_id="EP9999999A1", as_of_year=2023
    )
    assert result.signal("neighbour_density") is None
    assert result.signal("filing_trend_slope") is None
    assert result.signal("forward_citation_count").value == 2.0


def test_citing_entities_are_classified_corporate_vs_academic():
    client = make_client(
        citing=[
            CitingDoc("EP999A1", entity="Acme Corp"),          # corporate
            CitingDoc("EP998A1", entity="Stanford University"),  # academic
            CitingDoc("EP997A1"),                                # unknown applicant
        ]
    )
    result = stream(client).run(profile(["x"]), publication_id="EP9999999A1", as_of_year=2023)

    corp = result.signal("corporate_citation_count")
    assert corp is not None and corp.value == 1.0           # only Acme Corp
    assert "Acme Corp" in corp.detail
    assert "1 corporate, 1 academic" in result.signal("forward_citation_count").detail
    # the per-citation evidence is annotated with the classified kind
    fwd_evidence = [e for e in result.evidence() if "cites EP9999999A1" in e.snippet]
    assert any("corporate" in e.snippet for e in fwd_evidence)
    assert any("academic" in e.snippet for e in fwd_evidence)


def test_corporate_signal_carries_no_extra_evidence():
    # The corporate count is a derived aggregate; its evidence is the citations
    # already on forward_citation_count, so it must not duplicate evidence rows.
    result = stream(make_client()).run(
        profile(["x"]), publication_id="EP9999999A1", as_of_year=2023
    )
    assert result.signal("corporate_citation_count").evidence == []


def test_neighbour_density_counts_total_not_sample():
    client = make_client(
        search=SearchResult(total=137, hits=[SearchHit("EP1A1"), SearchHit("EP2A1")])
    )
    result = stream(client).run(profile(["x"]), as_of_year=2023)
    sig = result.signal("neighbour_density")
    assert sig.value == 137.0
    assert len(sig.evidence) == 2  # only the sampled hits become evidence
