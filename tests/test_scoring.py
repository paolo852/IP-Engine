"""L4 ventureability scoring: transparent, weighted, explainable, honest gaps."""

from __future__ import annotations

from forge.config import ScoringConfig, load_scoring_config
from forge.db.models import Asset, AssetType, Licence
from forge.scoring import ScoringInputs, score_ventureability
from forge.streams.base import EvidenceRecord, SourceSpec, StreamResult, SubSignal

CONFIG = load_scoring_config("config/scoring.yaml")


def ev(stream: str, snippet: str) -> EvidenceRecord:
    return EvidenceRecord(stream, 0.5, snippet, SourceSpec("x", Licence.public, "loc"))


def sub(name, value, evs=()):
    return SubSignal(name=name, value=value, detail="", evidence=list(evs))


def sr(stream, *subs):
    return StreamResult(stream=stream, sub_signals=list(subs))


def asset(legal_status="granted", key_dates=None):
    return Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        legal_status=legal_status,
        key_dates=key_dates or {"grant_date": "2022-06-21"},
    )


def full_inputs() -> ScoringInputs:
    return ScoringInputs(
        asset=asset(),
        stream_results=[
            sr(
                "S2_patents",
                sub("filing_trend_slope", 3.0, [ev("S2_patents", "Filings 2021-2023: [8,11,15] (slope +3.0/yr)")]),
                sub("forward_citation_count", 2.0, [ev("S2_patents", "EP9 cites EPX")]),
                sub("neighbour_density", 40.0, [ev("S2_patents", "Neighbouring patent EP1")]),
            ),
            sr("S3_roadmaps", sub("industrial_regulatory_pull", 4.0, [ev("S3_roadmaps", "roadmap: Photonics Roadmap (P21)")])),
            sr("S4_taxonomy", sub("eu_taxonomy:digital", 5.0, [ev("S4_taxonomy", "Aligns with EU digital: photonic")])),
        ],
    )


def test_full_score_is_weighted_and_covers_grounded_dimensions():
    score = score_ventureability(full_inputs(), CONFIG)

    # Four of six dimensions are grounded; two need data we don't have yet.
    assert score.coverage == 0.75
    assert 0.80 < score.value < 0.83  # documented weighted mean over scored dims

    assert score.dimension("technology_maturity").value == 1.0  # granted
    assert 0.95 <= score.dimension("market_pull").value <= 1.0
    assert 0.54 < score.dimension("ip_defensibility").value < 0.57
    assert score.dimension("regulatory_pathway").value == 0.5   # digital alignment


def test_capital_and_team_are_indeterminate_not_fabricated():
    score = score_ventureability(full_inputs(), CONFIG)
    assert score.dimension("capital_intensity").value is None
    assert score.dimension("team_availability").value is None
    assert "cost/TRL" in score.dimension("capital_intensity").rationale


def test_each_scored_dimension_exposes_its_evidence():
    score = score_ventureability(full_inputs(), CONFIG)
    assert score.dimension("technology_maturity").evidence  # legal_status ref
    assert any("S3_roadmaps" in e for e in score.dimension("market_pull").evidence)
    assert any("cites" in e or "Neighbouring" in e for e in score.dimension("ip_defensibility").evidence)


def test_no_signals_yield_indeterminate_overall():
    score = score_ventureability(
        ScoringInputs(asset=asset(legal_status=None), stream_results=[]), CONFIG
    )
    assert score.value is None and score.coverage == 0.0
    assert all(not d.scored for d in score.dimensions)


def test_weights_are_config_driven():
    base = score_ventureability(full_inputs(), CONFIG).value
    # Pour all weight onto ip_defensibility (the lowest-scoring grounded dim).
    skewed = ScoringConfig(
        weights={
            "technology_maturity": 0.0, "market_pull": 0.0, "ip_defensibility": 1.0,
            "capital_intensity": 0.0, "regulatory_pathway": 0.0, "team_availability": 0.0,
        },
        scaling=CONFIG.scaling,
    )
    assert score_ventureability(full_inputs(), skewed).value < base


def test_corporate_citations_strengthen_ip_defensibility():
    # Same citation count, but adding a corporate-adoption signal raises the
    # ip_defensibility score (corporate citations count double, by design).
    base_inputs = ScoringInputs(
        asset=asset(),
        stream_results=[sr("S2_patents", sub("forward_citation_count", 2.0, [ev("S2_patents", "EP9 cites EPX")]))],
    )
    corp_inputs = ScoringInputs(
        asset=asset(),
        stream_results=[
            sr(
                "S2_patents",
                sub("forward_citation_count", 2.0, [ev("S2_patents", "EP9 cites EPX")]),
                sub("corporate_citation_count", 2.0),
            )
        ],
    )
    base = score_ventureability(base_inputs, CONFIG).dimension("ip_defensibility")
    boosted = score_ventureability(corp_inputs, CONFIG).dimension("ip_defensibility")
    assert boosted.value > base.value
    assert "2 corporate" in boosted.rationale


def test_scaling_is_config_driven():
    lenient = ScoringConfig(weights=CONFIG.weights, scaling={**CONFIG.scaling, "citation_saturation": 1})
    strict = ScoringConfig(weights=CONFIG.weights, scaling={**CONFIG.scaling, "citation_saturation": 50})
    # Smaller saturation -> 2 citations count for more IP-validation credit.
    lo = score_ventureability(full_inputs(), strict).dimension("ip_defensibility").value
    hi = score_ventureability(full_inputs(), lenient).dimension("ip_defensibility").value
    assert hi > lo


def test_s1_funding_contributes_to_market_pull():
    # An asset with only S1 funding signal -> market_pull is grounded by it.
    inputs = ScoringInputs(
        asset=asset(),
        stream_results=[sr("S1_funding",
                           sub("funding_momentum", 10_000_000.0,
                               [ev("S1_funding", "€10.0M total funding across 5 rounds")]))],
    )
    mp = score_ventureability(inputs, CONFIG).dimension("market_pull")
    assert mp.value == 1.0  # at the funding reference -> full credit
    assert any("S1_funding" in e for e in mp.evidence)
    assert "funding=€10.0M" in mp.rationale


def test_named_regulation_lifts_regulatory_pathway():
    inputs = ScoringInputs(
        asset=asset(),
        stream_results=[sr("S3_roadmaps", sub("industrial_regulatory_pull", 2.0,
                                              [ev("S3_roadmaps", "regulation: AI Act (EC)")]))],
    )
    assert score_ventureability(inputs, CONFIG).dimension("regulatory_pathway").value == 0.8


def test_breakdown_is_explainable():
    text = score_ventureability(full_inputs(), CONFIG).breakdown()
    assert "ventureability:" in text
    assert "market_pull" in text and "capital_intensity (w=0.1): n/a" in text
