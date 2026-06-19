"""S2 — patents/citations cross-referencing (free; built first).

Answers: "is the field alive, and has industry already noticed THIS asset?" via
three sub-signals over EPO OPS:

* ``filing_trend_slope`` — is filing activity in the problem space rising?
* ``forward_citation_count`` (+ citing entities) — who has cited THIS asset?
* ``neighbour_density`` — how crowded is the problem space?

Queries are built from the profile's problem-space ``query_terms`` (not the
patent's own wording). The analysis is deterministic and unit-tested with a fake
client; ``OpsS2Client`` is the real, network-backed implementation.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from ..db.models import Licence
from ..enrichment.profiling import AssetProfile
from .analysis import clamp_unit, coverage, linear_slope
from .base import EvidenceRecord, SourceSpec, StreamResult, SubSignal
from .entities import CORPORATE, classify_entity, markers_from_config

STREAM = "S2_patents"
SOURCE_TYPE = "epo_ops"


# -- data shapes the client returns -----------------------------------------
@dataclass
class PatentQuery:
    """A typed query object derived from one problem-space term."""

    term: str
    cql: str  # OPS CQL expression


@dataclass
class SearchHit:
    publication_id: str
    title: str | None = None
    relevance: float = 1.0


@dataclass
class SearchResult:
    total: int
    hits: list[SearchHit] = field(default_factory=list)


@dataclass
class YearCount:
    year: int
    count: int


@dataclass
class CitingDoc:
    publication_id: str
    entity: str | None = None
    date: date | None = None


class S2Client(Protocol):
    def search(self, cql: str) -> SearchResult: ...
    def filings_by_year(self, cql: str, years: list[int]) -> list[YearCount]: ...
    def forward_citations(self, publication_id: str) -> list[CitingDoc]: ...


def _to_cql(term: str) -> str:
    """A single-term CQL clause searching title+abstract (txt)."""
    escaped = term.replace('"', " ").strip()
    return f'txt="{escaped}"'


def _espacenet(publication_id: str) -> str:
    q = urllib.parse.quote(f"pn={publication_id}")
    return f"https://worldwide.espacenet.com/patent/search?q={q}"


class S2PatentsStream:
    """Build queries from a profile, fan out via an S2Client, emit evidence."""

    def __init__(self, client: S2Client, *, config: dict) -> None:
        self.client = client
        self.window = int(config.get("filing_window_years", 5))
        self.max_neighbours = int(config.get("max_neighbours", 10))
        self._academic_markers, self._corporate_markers = markers_from_config(config)

    def queries(self, profile: AssetProfile) -> list[PatentQuery]:
        return [PatentQuery(term=t, cql=_to_cql(t)) for t in profile.query_terms if t.strip()]

    def run(
        self,
        profile: AssetProfile,
        *,
        publication_id: str | None = None,
        as_of_year: int | None = None,
    ) -> StreamResult:
        result = StreamResult(stream=STREAM)

        queries = self.queries(profile)
        if queries:
            combined = " or ".join(q.cql for q in queries)
            result.sub_signals.append(self._neighbour_signal(self.client.search(combined)))
            years = self._window_years(as_of_year)
            counts = self.client.filings_by_year(combined, years)
            result.sub_signals.append(self._filing_trend_signal(counts))

        if publication_id:
            citing = self.client.forward_citations(publication_id)
            result.sub_signals.append(self._forward_citation_signal(publication_id, citing))
            result.sub_signals.append(self._corporate_citation_signal(citing))

        return result

    def _classify(self, entity: str | None) -> str:
        return classify_entity(
            entity,
            academic_markers=self._academic_markers,
            corporate_markers=self._corporate_markers,
        )

    # -- sub-signal builders -------------------------------------------------
    def _neighbour_signal(self, search: SearchResult) -> SubSignal:
        sample = search.hits[: self.max_neighbours]
        evidence = [
            EvidenceRecord(
                stream=STREAM,
                match_strength=clamp_unit(hit.relevance),
                snippet=f"Neighbouring patent {hit.publication_id}"
                + (f": {hit.title}" if hit.title else ""),
                link=_espacenet(hit.publication_id),
                source=SourceSpec(SOURCE_TYPE, Licence.free, hit.publication_id),
            )
            for hit in sample
        ]
        return SubSignal(
            name="neighbour_density",
            value=float(search.total),
            detail=f"{search.total} patents in the problem space "
            f"({len(sample)} sampled as evidence)",
            evidence=evidence,
        )

    def _filing_trend_signal(self, counts: list[YearCount]) -> SubSignal:
        ordered = sorted(counts, key=lambda c: c.year)
        slope = linear_slope([(c.year, c.count) for c in ordered])
        if not ordered:
            return SubSignal("filing_trend_slope", 0.0, "no filing data", [])
        detail = (
            f"Filings {ordered[0].year}-{ordered[-1].year}: "
            f"{[c.count for c in ordered]} (slope {slope:+.2f}/yr)"
        )
        confidence = coverage(len(ordered), self.window)
        evidence = [
            EvidenceRecord(
                stream=STREAM,
                match_strength=clamp_unit(confidence),
                snippet=detail,
                source=SourceSpec(SOURCE_TYPE, Licence.free, "epo_ops:filing-trend"),
            )
        ]
        return SubSignal("filing_trend_slope", slope, detail, evidence)

    def _forward_citation_signal(
        self, publication_id: str, citing: list[CitingDoc]
    ) -> SubSignal:
        entities = sorted({c.entity for c in citing if c.entity})
        evidence = [
            EvidenceRecord(
                stream=STREAM,
                match_strength=1.0,  # a direct citation of THIS asset is maximally relevant
                snippet=f"{c.publication_id} cites {publication_id}"
                + (f" (applicant: {c.entity}, {self._classify(c.entity)})" if c.entity else ""),
                link=_espacenet(c.publication_id),
                source=SourceSpec(SOURCE_TYPE, Licence.free, c.publication_id),
                observed_at=_to_dt(c.date),
            )
            for c in citing
        ]
        kinds = [self._classify(c.entity) for c in citing if c.entity]
        corp = kinds.count(CORPORATE)
        acad = kinds.count("academic")
        detail = f"{len(citing)} forward citation(s)"
        if entities:
            detail += f"; citing entities: {', '.join(entities)}"
        if kinds:
            detail += f" ({corp} corporate, {acad} academic)"
        return SubSignal("forward_citation_count", float(len(citing)), detail, evidence)

    def _corporate_citation_signal(self, citing: list[CitingDoc]) -> SubSignal:
        """Industry-adoption signal: how many citing applicants are companies.

        Carried as a separate, transparently-named sub-signal (no own evidence —
        the citations live on ``forward_citation_count``) so the scorer can weight
        corporate adoption explicitly rather than treating all citations alike.
        """
        corp = [c for c in citing if self._classify(c.entity) == CORPORATE]
        names = sorted({c.entity for c in corp if c.entity})
        detail = f"{len(corp)} of {len(citing)} forward citation(s) from companies"
        if names:
            detail += f": {', '.join(names)}"
        return SubSignal("corporate_citation_count", float(len(corp)), detail, [])

    def _window_years(self, as_of_year: int | None) -> list[int]:
        end = as_of_year or date.today().year
        return list(range(end - self.window + 1, end + 1))


def _to_dt(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)


# -- OPS search parsing + network-backed client -----------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_search(payload: bytes | str) -> SearchResult:
    """Parse an OPS published-data search response into a SearchResult."""
    root = ET.fromstring(payload)
    total = 0
    for el in root.iter():
        if _local(el.tag) == "biblio-search":
            total = int(el.get("total-result-count", "0"))
            break

    hits: list[SearchHit] = []
    for pubref in (e for e in root.iter() if _local(e.tag) == "publication-reference"):
        docdb = next(
            (
                c
                for c in pubref.iter()
                if _local(c.tag) == "document-id" and c.get("document-id-type") == "docdb"
            ),
            None,
        )
        if docdb is None:
            continue
        parts = {_local(c.tag): (c.text or "").strip() for c in docdb}
        country, number, kind = parts.get("country"), parts.get("doc-number"), parts.get("kind")
        if country and number:
            hits.append(SearchHit(publication_id=f"{country}{number}{kind or ''}"))
    return SearchResult(total=total, hits=hits)


def parse_citing(payload: bytes | str) -> list[CitingDoc]:
    """Parse an OPS biblio search response into citing docs with applicants.

    The biblio search endpoint returns ``exchange-document`` entries carrying both
    the publication reference and the parties; we pair each citing publication id
    with its first applicant name so the entity classifier (E4) can tell corporate
    from academic adoption. Falls back to bare references (no applicant) when the
    response is a plain search result.
    """
    root = ET.fromstring(payload)
    docs = [e for e in root.iter() if _local(e.tag) == "exchange-document"]
    if not docs:
        # Plain (non-biblio) search response — references only, no applicants.
        return [CitingDoc(publication_id=hit.publication_id) for hit in parse_search(payload).hits]

    citing: list[CitingDoc] = []
    for doc in docs:
        pub_id = _docdb_id(doc)
        if pub_id is None:
            continue
        citing.append(CitingDoc(publication_id=pub_id, entity=_first_applicant(doc)))
    return citing


def _docdb_id(element: ET.Element) -> str | None:
    """First docdb publication id (country+number+kind) under ``element``."""
    for pubref in (e for e in element.iter() if _local(e.tag) == "publication-reference"):
        docdb = next(
            (
                c
                for c in pubref.iter()
                if _local(c.tag) == "document-id" and c.get("document-id-type") == "docdb"
            ),
            None,
        )
        if docdb is None:
            continue
        parts = {_local(c.tag): (c.text or "").strip() for c in docdb}
        country, number, kind = parts.get("country"), parts.get("doc-number"), parts.get("kind")
        if country and number:
            return f"{country}{number}{kind or ''}"
    return None


def _first_applicant(doc: ET.Element) -> str | None:
    """First applicant name under an exchange-document's parties, if any."""
    for applicant in (e for e in doc.iter() if _local(e.tag) == "applicant"):
        name = next((c for c in applicant.iter() if _local(c.tag) == "name"), None)
        if name is not None and (name.text or "").strip():
            return name.text.strip()
    return None


class OpsS2Client:
    """S2Client backed by the live EPO OPS search API (free, network)."""

    def __init__(self, ops_client) -> None:
        self._ops = ops_client
        self._base = ops_client.settings.base_url

    def _search(self, cql: str) -> SearchResult:
        url = f"{self._base}/published-data/search?q={urllib.parse.quote(cql)}"
        body, _content_type = self._ops.fetch(url, ref=cql)
        return parse_search(body)

    def search(self, cql: str) -> SearchResult:
        return self._search(cql)

    def filings_by_year(self, cql: str, years: list[int]) -> list[YearCount]:
        out: list[YearCount] = []
        for year in years:
            res = self._search(f'{cql} and pd within "{year}"')
            out.append(YearCount(year, res.total))
        return out

    def forward_citations(self, publication_id: str) -> list[CitingDoc]:
        # The biblio endpoint returns applicants too, so citing entities can be
        # classified corporate vs academic (E4).
        cql = f"ct={publication_id}"
        url = f"{self._base}/published-data/search/biblio?q={urllib.parse.quote(cql)}"
        body, _content_type = self._ops.fetch(url, ref=cql)
        return parse_citing(body)
