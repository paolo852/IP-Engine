"""L4 ventureability scoring — a transparent, config-weighted function.

The ventureability score is a documented weighted sum over six dimensions, with
config-set weights (rule 2). There is NO black-box ML: each dimension is computed
from named stream signals and asset fields by a documented rule, and exposes the
evidence records that produced it (spec requirement) plus a plain-text rationale.

Honesty over completeness: a dimension with no supporting signal is reported as
*indeterminate* (value None), never given a fabricated number. The overall score
is the weighted mean over the dimensions that COULD be grounded, and reports its
coverage (the share of total weight that was scorable). capital_intensity and
team_availability are indeterminate today — they need S1 (funding) / internal
team data that later slices supply.

Humans decide; this only ranks and evidences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .config import ScoringConfig
from .db.models import Asset
from .streams.analysis import clamp_unit
from .streams.base import StreamResult

# Reference defaults if config omits a scaling key (kept in sync with scoring.yaml).
_DEFAULT_SCALING = {
    "market_pull_reference": 3,
    "filing_slope_reference": 3.0,
    "citation_saturation": 5,
    "neighbour_crowded": 100,
    "funding_reference_eur": 10_000_000,
}


@dataclass
class ScoringInputs:
    """What the scorer reads. Stream results are the in-memory StreamResults."""

    asset: Asset
    stream_results: list[StreamResult] = field(default_factory=list)


@dataclass
class DimensionScore:
    dimension: str
    value: float | None  # [0, 1], or None when indeterminate
    rationale: str
    evidence: list[str] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.value is not None


@dataclass
class VentureabilityScore:
    value: float | None  # overall [0, 1], None if nothing could be scored
    coverage: float  # share of total weight that was scorable
    dimensions: list[DimensionScore]
    weights: dict[str, float]

    def dimension(self, name: str) -> DimensionScore | None:
        return next((d for d in self.dimensions if d.dimension == name), None)

    def breakdown(self) -> str:
        if self.value is None:
            head = "ventureability: indeterminate (no scorable dimensions)"
        else:
            head = f"ventureability: {self.value:.2f} (coverage {self.coverage:.0%})"
        lines = [head]
        for dim in self.dimensions:
            w = self.weights[dim.dimension]
            shown = f"{dim.value:.2f}" if dim.scored else "n/a"
            lines.append(f"  {dim.dimension} (w={w:g}): {shown} — {dim.rationale}")
            for ev in dim.evidence:
                lines.append(f"      • {ev}")
        return "\n".join(lines)


# -- signal helpers ---------------------------------------------------------
def _signal(results: Iterable[StreamResult], name: str) -> float | None:
    for result in results:
        sig = result.signal(name)
        if sig is not None:
            return sig.value
    return None


def _aligned_categories(results: Iterable[StreamResult]) -> list[str]:
    return [
        s.name
        for r in results
        for s in r.sub_signals
        if s.name.startswith("eu_taxonomy:")
    ]


def _evidence(results, streams: set[str], predicate=None) -> list[str]:
    out: list[str] = []
    for r in results:
        if r.stream not in streams:
            continue
        for e in r.evidence():
            if predicate is None or predicate(e):
                out.append(f"[{r.stream}] {e.snippet}")
    return out


def _saturating(x: float, k: float) -> float:
    return x / (x + k) if (x + k) > 0 else 0.0


def _blend(components: list[tuple[float, float]]) -> float:
    """Weighted mean of present (weight, score) components, renormalised."""
    total_w = sum(w for w, _ in components)
    return sum(w * s for w, s in components) / total_w


# -- dimension scorers ------------------------------------------------------
def _market_pull(inp: ScoringInputs, sc: dict) -> DimensionScore:
    r = inp.stream_results
    pull = _signal(r, "industrial_regulatory_pull")
    slope = _signal(r, "filing_trend_slope")
    funding = _signal(r, "funding_momentum")
    aligned = bool(_aligned_categories(r))

    components: list[tuple[float, float]] = []
    if pull is not None:
        components.append((0.4, clamp_unit(pull / sc["market_pull_reference"])))
    if funding is not None:
        components.append((0.4, clamp_unit(funding / sc["funding_reference_eur"])))
    if slope is not None:
        components.append((0.3, clamp_unit(max(slope, 0.0) / sc["filing_slope_reference"])))
    if aligned:
        components.append((0.2, 1.0))

    if not components:
        return DimensionScore("market_pull", None, "no S1/S2/S3/S4 pull signals", [])
    evidence = _evidence(r, {"S1_funding", "S3_roadmaps", "S4_taxonomy"}) + _evidence(
        r, {"S2_patents"}, lambda e: e.snippet.startswith("Filings")
    )
    return DimensionScore(
        "market_pull",
        clamp_unit(_blend(components)),
        f"pull={int(pull) if pull is not None else 'n/a'}, "
        f"funding={f'€{funding/1e6:.1f}M' if funding is not None else 'n/a'}, "
        f"slope={slope if slope is not None else 'n/a'}, eu_aligned={aligned}",
        evidence,
    )


def _ip_defensibility(inp: ScoringInputs, sc: dict) -> DimensionScore:
    r = inp.stream_results
    cites = _signal(r, "forward_citation_count")
    corp = _signal(r, "corporate_citation_count")
    # Field crowdedness from the problem-space text search, falling back to the
    # IPC class-based neighbourhood when the text queries returned nothing (E4).
    density = _signal(r, "neighbour_density")
    if density is None:
        density = _signal(r, "class_neighbour_density")
    legal = inp.asset.legal_status

    components: list[tuple[float, float]] = []
    if cites is not None:
        # A forward citation shows the field noticed the asset; a CORPORATE
        # citation shows *industry* (not just academia) noticed it — a stronger
        # adoption/defensibility signal, so corporate citations count double (E4).
        effective = cites + (corp or 0.0)
        components.append((0.4, _saturating(effective, sc["citation_saturation"])))
    if density is not None:
        components.append((0.4, 1.0 - clamp_unit(density / sc["neighbour_crowded"])))
    if legal:
        legal_score = 1.0 if "grant" in legal.lower() else 0.5
        components.append((0.2, legal_score))

    if not components:
        return DimensionScore("ip_defensibility", None, "no citation/neighbour/legal signal", [])
    evidence = _evidence(
        r,
        {"S2_patents"},
        lambda e: "cites" in e.snippet
        or e.snippet.startswith("Neighbouring")
        or e.snippet.startswith("Same-class"),
    )
    if legal:
        evidence.append(f"asset.legal_status='{legal}'")
    return DimensionScore(
        "ip_defensibility",
        clamp_unit(_blend(components)),
        f"citations={int(cites) if cites is not None else 'n/a'}"
        f"{f' ({int(corp)} corporate)' if corp else ''}, "
        f"neighbours={int(density) if density is not None else 'n/a'}, legal={legal!r}",
        evidence,
    )


def _technology_maturity(inp: ScoringInputs, sc: dict) -> DimensionScore:
    legal = inp.asset.legal_status
    if not legal:
        return DimensionScore(
            "technology_maturity", None, "no legal_status to gauge maturity", []
        )
    ls = legal.lower()
    if "grant" in ls:
        value, note = 1.0, "granted patent (proven, examined)"
    elif any(w in ls for w in ("pending", "application", "filed", "publish")):
        value, note = 0.5, "application/pending (unexamined)"
    else:
        value, note = 0.5, f"legal_status {legal!r}"
    evidence = [f"asset.legal_status='{legal}'"]
    key_dates = inp.asset.key_dates or {}
    if key_dates.get("grant_date"):
        evidence.append(f"asset.key_dates.grant_date={key_dates['grant_date']}")
    return DimensionScore("technology_maturity", value, note, evidence)


def _regulatory_pathway(inp: ScoringInputs, sc: dict) -> DimensionScore:
    r = inp.stream_results
    reg_evidence = _evidence(
        r, {"S3_roadmaps"}, lambda e: e.snippet.startswith("regulation:")
    )
    aligned = _aligned_categories(r)

    if reg_evidence:
        return DimensionScore(
            "regulatory_pathway", 0.8,
            "named regulation(s) in the problem space — pathway identified",
            reg_evidence,
        )
    if any(("critical_tech" in c or "green" in c) for c in aligned):
        return DimensionScore(
            "regulatory_pathway", 0.6,
            "aligns with a regulated EU priority (green / critical-tech)",
            _evidence(r, {"S4_taxonomy"}),
        )
    if aligned:
        return DimensionScore(
            "regulatory_pathway", 0.5,
            "aligns with an EU digital priority",
            _evidence(r, {"S4_taxonomy"}),
        )
    return DimensionScore(
        "regulatory_pathway", None, "no regulatory/taxonomy signal", []
    )


def _capital_intensity(inp: ScoringInputs, sc: dict) -> DimensionScore:
    # Capital intensity is cost-to-build, not capital *available* (that is S1's
    # market_pull). No cost/TRL signal is wired yet, so this stays indeterminate.
    return DimensionScore(
        "capital_intensity", None,
        "no cost/TRL signal yet (capital intensity != funding availability)", [],
    )


def _team_availability(inp: ScoringInputs, sc: dict) -> DimensionScore:
    return DimensionScore(
        "team_availability", None,
        "no team-availability data (needs internal HR/inventor-status input)", [],
    )


_SCORERS = (
    _technology_maturity,
    _market_pull,
    _ip_defensibility,
    _capital_intensity,
    _regulatory_pathway,
    _team_availability,
)


def _scaling(config: ScoringConfig) -> dict:
    merged = dict(_DEFAULT_SCALING)
    merged.update(config.scaling or {})
    return merged


def score_ventureability(
    inputs: ScoringInputs, config: ScoringConfig
) -> VentureabilityScore:
    """Compute the explainable, config-weighted ventureability score."""
    sc = _scaling(config)
    dimensions = [scorer(inputs, sc) for scorer in _SCORERS]
    weights = config.weights

    scored = [d for d in dimensions if d.scored]
    covered = sum(weights[d.dimension] for d in scored)
    if covered <= 0:
        return VentureabilityScore(None, 0.0, dimensions, weights)
    value = sum(weights[d.dimension] * d.value for d in scored) / covered
    return VentureabilityScore(clamp_unit(value), covered, dimensions, weights)
