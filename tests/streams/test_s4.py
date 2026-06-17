"""S4 EU-taxonomy classifier: deterministic alignment + evidence."""

from __future__ import annotations

from forge.config import TaxonomyConfig, load_taxonomy_config
from forge.streams.s4_taxonomy import S4TaxonomyStream

from .fakes import profile

CONFIG = load_taxonomy_config("config/taxonomy.yaml")


def test_digital_alignment_lists_matched_terms():
    p = profile(
        ["optical interconnect"],
        problem="High energy per bit in chip interconnects",
        solution="A micro-ring modulator photonic interconnect for edge computing",
    )
    result = S4TaxonomyStream(CONFIG).run(p)

    digital = result.signal("eu_taxonomy:digital")
    assert digital is not None
    matched = digital.detail
    assert "photonic" in matched and "optical" in matched and "edge computing" in matched
    assert digital.value == 3.0
    # No green/critical-tech alignment for this asset.
    assert result.signal("eu_taxonomy:green") is None


def test_match_strength_scales_to_strong_match_count():
    # One matched term, strong_match_count=3 -> strength 1/3.
    cfg = TaxonomyConfig(
        categories={"digital": {"label": "Digital", "terms": ("photonic",)}},
        strong_match_count=3,
    )
    result = S4TaxonomyStream(cfg).run(profile([], solution="a photonic device"))
    ev = result.signal("eu_taxonomy:digital").evidence[0]
    assert abs(ev.match_strength - 1 / 3) < 1e-9
    assert ev.source.licence.value == "public"


def test_word_boundaries_prevent_false_matches():
    cfg = TaxonomyConfig(
        categories={"digital": {"label": "Digital", "terms": ("ai", "5g")}},
        strong_match_count=3,
    )
    # "rain" must not match "ai"; "5gb" must not match "5g".
    result = S4TaxonomyStream(cfg).run(profile([], problem="heavy rain and 5gb files"))
    assert result.sub_signals == []
    # But a real "edge AI" and "5G" do match.
    result2 = S4TaxonomyStream(cfg).run(profile([], problem="edge AI over 5G"))
    assert {t for t in ("ai", "5g")} <= set(
        result2.signal("eu_taxonomy:digital").detail.split(": ")[-1].split(", ")
    )


def test_green_alignment_independent_of_digital():
    p = profile([], solution="solar photovoltaic with battery storage and recycling")
    result = S4TaxonomyStream(CONFIG).run(p)
    green = result.signal("eu_taxonomy:green")
    assert green is not None and green.value >= 3.0


def test_no_alignment_yields_no_signals():
    p = profile([], problem="a wooden chair", solution="four legs and a seat")
    assert S4TaxonomyStream(CONFIG).run(p).sub_signals == []
