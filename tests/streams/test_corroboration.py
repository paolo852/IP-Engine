"""Cross-stream corroboration: agreement vs conflict -> routing."""

from __future__ import annotations

from forge.config import load_corroboration_config
from forge.streams.base import StreamResult, SubSignal
from forge.streams.corroboration import Routing, corroborate

CONFIG = load_corroboration_config("config/corroboration.yaml")


def sig(name: str, value: float) -> SubSignal:
    return SubSignal(name=name, value=value, detail="")


def result(stream: str, *signals: SubSignal) -> StreamResult:
    return StreamResult(stream=stream, sub_signals=list(signals))


def test_corroborating_streams_route_to_sprint():
    results = [
        result(
            "S2_patents",
            sig("filing_trend_slope", 2.5),       # rising
            sig("forward_citation_count", 6),     # strong attention
            sig("neighbour_density", 40),         # moderate, not crowded
        ),
        result("S3_roadmaps", sig("industrial_regulatory_pull", 4)),  # strong pull
        result("S4_taxonomy", sig("eu_taxonomy:digital", 5)),         # EU aligned
    ]
    c = corroborate(results, CONFIG)
    assert c.routing is Routing.SPRINT
    assert len(c.agreements) >= 3
    assert not c.conflicts


def test_pull_into_crowded_field_without_citations_routes_to_licence_or_park():
    results = [
        result(
            "S2_patents",
            sig("filing_trend_slope", 3.0),       # field rising...
            sig("forward_citation_count", 0),     # ...but nobody cites THIS asset
            sig("neighbour_density", 150),        # crowded
        ),
        result("S3_roadmaps", sig("industrial_regulatory_pull", 4)),  # strong pull
        result("S4_taxonomy", sig("eu_taxonomy:digital", 3)),
    ]
    c = corroborate(results, CONFIG)
    assert c.routing is Routing.LICENCE_OR_PARK
    assert c.conflicts and "no forward citations" in c.conflicts[0]


def test_capital_flow_is_a_favourable_indicator():
    results = [
        result("S2_patents",
               sig("filing_trend_slope", 2.0), sig("forward_citation_count", 5),
               sig("neighbour_density", 40)),
        result("S1_funding", sig("funding_momentum", 30_000_000)),  # strong capital
    ]
    c = corroborate(results, CONFIG)
    assert c.indicator("capital_flow").level == "strong"
    assert "capital_flow" in c.agreements
    assert c.routing is Routing.SPRINT


def test_capital_into_crowded_field_without_citations_is_a_conflict():
    results = [
        result("S2_patents",
               sig("filing_trend_slope", 1.0), sig("forward_citation_count", 0),
               sig("neighbour_density", 150)),  # crowded, uncited
        result("S1_funding", sig("funding_momentum", 25_000_000)),  # strong capital
    ]
    c = corroborate(results, CONFIG)
    assert c.routing is Routing.LICENCE_OR_PARK
    assert c.conflicts and "no forward citations" in c.conflicts[0]


def test_single_positive_signal_routes_to_watch():
    results = [result("S4_taxonomy", sig("eu_taxonomy:green", 2))]
    c = corroborate(results, CONFIG)
    assert c.routing is Routing.WATCH
    assert c.agreements == ["eu_alignment"]


def test_no_favourable_signals_routes_to_park():
    results = [
        result(
            "S2_patents",
            sig("filing_trend_slope", -2.0),   # declining
            sig("forward_citation_count", 0),
            sig("neighbour_density", 5),        # sparse
        )
    ]
    c = corroborate(results, CONFIG)
    assert c.routing is Routing.PARK
    assert c.agreements == []


def test_indicator_levels_are_config_driven():
    results = [result("S2_patents", sig("filing_trend_slope", 1.5))]
    # Default rising_min_slope is 1.0 -> 1.5 reads as rising.
    assert corroborate(results, CONFIG).indicator("field_momentum").level == "rising"

    from forge.config import CorroborationConfig

    strict = CorroborationConfig(
        indicators={
            **CONFIG.indicators,
            "field_momentum": {"rising_min_slope": 5.0, "declining_max_slope": -1.0},
        }
    )
    # Same slope, stricter threshold -> now merely flat.
    assert corroborate(results, strict).indicator("field_momentum").level == "flat"


def test_missing_streams_yield_unknown_indicators_not_crashes():
    c = corroborate([], CONFIG)
    assert c.routing is Routing.PARK
    assert c.indicator("field_momentum").level == "unknown"
    assert c.indicator("industry_attention").level == "unknown"


def test_explanation_lists_indicators_and_conflicts():
    results = [
        result(
            "S2_patents",
            sig("filing_trend_slope", 1.0),
            sig("forward_citation_count", 0),
            sig("neighbour_density", 200),
        ),
        result("S3_roadmaps", sig("industrial_regulatory_pull", 5)),
    ]
    text = corroborate(results, CONFIG).explanation()
    assert "routing: licence_or_park" in text
    assert "CONFLICT:" in text
    assert "field_crowding: crowded" in text
