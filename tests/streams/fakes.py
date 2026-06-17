"""Test doubles + builders for the S2 stream — no network."""

from __future__ import annotations

from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.streams.s2_patents import CitingDoc, SearchResult, YearCount


def profile(
    query_terms: list[str],
    *,
    problem: str = "p",
    solution: str = "s",
    applications: tuple[str, ...] = (),
) -> AssetProfile:
    def g(name, value):
        return GroundedField(name=name, value=value, quote="q", source_field="abstract")

    return AssetProfile(
        problem=g("problem", problem),
        solution=g("solution", solution),
        applications=[g(f"application[{i}]", a) for i, a in enumerate(applications)],
        query_terms=query_terms,
        model="m",
    )


class FakeS2Client:
    """Returns canned search/citation data and records every query made."""

    def __init__(
        self,
        *,
        search: SearchResult,
        year_counts: list[YearCount],
        citing: list[CitingDoc],
    ) -> None:
        self._search = search
        self._year_counts = year_counts
        self._citing = citing
        self.calls: list[tuple] = []

    def search(self, cql: str) -> SearchResult:
        self.calls.append(("search", cql))
        return self._search

    def filings_by_year(self, cql: str, years: list[int]) -> list[YearCount]:
        self.calls.append(("filings_by_year", cql, tuple(years)))
        return self._year_counts

    def forward_citations(self, publication_id: str) -> list[CitingDoc]:
        self.calls.append(("forward_citations", publication_id))
        return self._citing
