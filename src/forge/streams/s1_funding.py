"""S1 — funding flows (Dealroom/Crunchbase). LICENSED — built last.

Answers: "is capital flowing into this problem now?" by aggregating recent
funding rounds in the asset's problem space.

LICENCE SEPARATION (rule 5): this stream persists only DERIVED aggregates —
total funding, round count, the set of active investors — as evidence with a
``licensed_dealroom`` source and a pointer locator. The raw per-round records
(company, amount, per-round investors) are used only in memory to compute those
aggregates and are NEVER turned into evidence or stored; nothing here would
require republishing licensed raw records.

The analysis is deterministic and unit-tested with a fake client; the
Dealroom-backed client is network-isolated and reads its key from the
environment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from ..db.models import Licence
from ..enrichment.profiling import AssetProfile
from .base import EvidenceRecord, SourceSpec, StreamResult, SubSignal

STREAM = "S1_funding"
SOURCE_TYPE = "dealroom"
API_KEY_ENV = "FORGE_DEALROOM_API_KEY"


@dataclass
class FundingQuery:
    """A typed query object derived from one problem-space term."""

    term: str
    query: str


@dataclass
class FundingRound:
    """A single round — used IN MEMORY only; never persisted (licensed raw)."""

    org: str
    amount_eur: float | None = None
    year: int | None = None
    investors: list[str] = field(default_factory=list)


@dataclass
class FundingSearch:
    """Aggregates for a query. Only the aggregates leave this stream as evidence."""

    total_amount_eur: float
    round_count: int
    investors: list[str] = field(default_factory=list)  # derived, de-duplicated
    rounds: list[FundingRound] = field(default_factory=list)  # in-memory only


class S1Client(Protocol):
    def search_funding(self, query: str, *, years: list[int]) -> FundingSearch: ...


class S1FundingStream:
    """Build problem-space queries, fan out via an S1Client, emit DERIVED evidence."""

    def __init__(self, client: S1Client, *, config: dict) -> None:
        self.client = client
        self.window = int(config.get("funding_window_years", 3))
        self.max_investors = int(config.get("max_investors", 10))

    def queries(self, profile: AssetProfile) -> list[FundingQuery]:
        return [FundingQuery(t, t) for t in profile.query_terms if t.strip()]

    def _years(self, as_of_year: int | None) -> list[int]:
        end = as_of_year or date.today().year
        return list(range(end - self.window + 1, end + 1))

    def run(self, profile: AssetProfile, *, as_of_year: int | None = None) -> StreamResult:
        result = StreamResult(stream=STREAM)
        queries = self.queries(profile)
        if not queries:
            return result

        years = self._years(as_of_year)
        combined = " ".join(q.query for q in queries)
        search = self.client.search_funding(combined, years=years)

        # The provenance reflects the client: licensed Dealroom, or the synthetic
        # mock used by default (licence separation, rule 5).
        source_type = getattr(self.client, "source_type", SOURCE_TYPE)
        licence = getattr(self.client, "licence", Licence.licensed_dealroom)

        money_m = search.total_amount_eur / 1e6
        funding_ev = EvidenceRecord(
            stream=STREAM,
            match_strength=1.0,
            snippet=(
                f"€{money_m:.1f}M total funding across {search.round_count} rounds "
                f"({years[0]}-{years[-1]})"
            ),
            source=SourceSpec(source_type, licence, f"{source_type}:funding:{combined}"),
        )
        result.sub_signals.append(
            SubSignal(
                "funding_momentum",
                float(search.total_amount_eur),
                f"€{money_m:.1f}M across {search.round_count} rounds",
                [funding_ev],
            )
        )

        investors = search.investors[: self.max_investors]
        if investors:
            inv_ev = EvidenceRecord(
                stream=STREAM,
                match_strength=1.0,
                snippet="Active investors: " + ", ".join(investors),
                source=SourceSpec(
                    source_type, licence, f"{source_type}:investors:{combined}"
                ),
            )
            result.sub_signals.append(
                SubSignal(
                    "notable_investors",
                    float(len(investors)),
                    "investors: " + ", ".join(investors),
                    [inv_ev],
                )
            )

        return result


def parse_funding(payload: bytes | str) -> FundingSearch:
    """Parse a Dealroom-shaped JSON response into aggregates (derived investors)."""
    data = json.loads(payload)
    rounds = [
        FundingRound(
            org=r.get("company", ""),
            amount_eur=r.get("amount_eur"),
            year=r.get("year"),
            investors=list(r.get("investors", [])),
        )
        for r in data.get("rounds", [])
    ]
    investors: list[str] = []
    for r in rounds:
        for inv in r.investors:
            if inv and inv not in investors:
                investors.append(inv)
    return FundingSearch(
        total_amount_eur=float(data.get("total_funding_eur", 0) or 0),
        round_count=int(data.get("round_count", len(rounds))),
        investors=investors,
        rounds=rounds,
    )


_MOCK_INVESTORS = (
    "Northbridge Ventures", "Helios Capital", "EU Deep-Tech Fund", "Kepler Partners",
    "Atlas Seed", "Meridian Growth", "Photon Ventures", "Greenfield Capital",
)


class MockS1Client:
    """Default S1Client: deterministic SYNTHETIC funding data, no licence needed.

    Lets the funding stream run out of the box (E5) without a Dealroom licence.
    Output is reproducible from the query and clearly marked synthetic (its
    evidence carries a ``synthetic`` licence and a ``mock:funding`` source), so it
    is never mistaken for licensed raw data (rule 5). Swapping in the real
    ``DealroomS1Client`` is a config/credential change.
    """

    source_type = "mock:funding"
    licence = Licence.synthetic

    def search_funding(self, query: str, *, years: list[int]) -> FundingSearch:
        import hashlib

        h = int(hashlib.sha256(query.strip().lower().encode()).hexdigest(), 16)
        total = float((h % 45 + 1) * 1_000_000)  # €1M–45M
        rounds = h % 6 + 1
        n_inv = h % 4  # 0–3 investors
        investors = [_MOCK_INVESTORS[(h >> (i * 5)) % len(_MOCK_INVESTORS)] for i in range(n_inv)]
        # De-duplicate while preserving order.
        seen: list[str] = []
        for inv in investors:
            if inv not in seen:
                seen.append(inv)
        return FundingSearch(total_amount_eur=total, round_count=rounds, investors=seen)


class DealroomS1Client:
    """S1Client backed by the licensed Dealroom API (network; key from env)."""

    def __init__(self, transport, *, base_url: str, api_key: str | None = None) -> None:
        self._transport = transport
        self._base = base_url.rstrip("/")
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)

    def search_funding(self, query: str, *, years: list[int]) -> FundingSearch:
        if not self._key:
            raise RuntimeError(f"missing Dealroom credentials: set {API_KEY_ENV}")
        body = json.dumps({"keywords": query, "years": years}).encode()
        resp = self._transport.request(
            "POST",
            f"{self._base}/funding-rounds/search",
            headers={"Authorization": f"Token {self._key}", "Content-Type": "application/json"},
            data=body,
            timeout=30,
        )
        if resp.status != 200:
            raise RuntimeError(f"Dealroom error: HTTP {resp.status}")
        return parse_funding(resp.body)
