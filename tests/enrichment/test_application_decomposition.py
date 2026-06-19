"""E1: application decomposition — market apps in industry language drive queries."""

from __future__ import annotations

import json

from forge.enrichment.profiling import build_profile
from forge.repository import get_profile, save_asset, save_profile

from .fakes import FakeProvider
from ..synthetic.assets import synthetic_patent_bundle

# Quotes are verbatim substrings of the synthetic patent's text; the market
# applications are in INDUSTRY language with their own industry_terms.
_STRUCTURED = json.dumps(
    {
        "technology_summary": "Silicon-photonics micro-ring optical interconnect.",
        "problem": {"value": "Inter-chip energy is too high for dense AI compute",
                    "quote": "reducing inter-chip energy per bit"},
        "solution": {"value": "Optical interconnect on a silicon waveguide",
                     "quote": "micro-ring modulator array coupled to a silicon waveguide"},
        "applications": [
            {"value": "Data-centre optical interconnects", "quote": "photonic interconnect",
             "end_customer": "hyperscale data centres", "use_case": "rack-scale links",
             "industry_terms": ["co-packaged optics", "silicon photonics transceiver"]},
            {"value": "Edge AI accelerator I/O", "quote": "edge inference workloads",
             "end_customer": "edge-AI chip makers", "use_case": "accelerator interconnect",
             "industry_terms": ["edge AI accelerator", "chiplet optical link"]},
            {"value": "HPC interconnect fabrics", "quote": "silicon waveguide",
             "end_customer": "supercomputing integrators", "use_case": "node fabric",
             "industry_terms": ["HPC optical fabric", "optical I/O"]},
        ],
        "query_terms": ["optical interconnect market"],
    }
)


def _profile():
    return build_profile(synthetic_patent_bundle().asset, FakeProvider(_STRUCTURED))


def test_profiler_emits_three_market_applications():
    profile = _profile()
    assert len(profile.applications) >= 3
    for app in profile.applications:
        assert app.industry_terms  # each carries industry search terms
        assert app.end_customer and app.use_case
    assert profile.technology_summary


def test_query_terms_are_market_not_technical():
    profile = _profile()
    # The stream queries are the applications' industry terms, not claim language.
    assert "co-packaged optics" in profile.query_terms
    assert "edge AI accelerator" in profile.query_terms
    assert all("micro-ring modulator" not in t for t in profile.query_terms)
    # The extra model query term is included too.
    assert "optical interconnect market" in profile.query_terms


def test_backward_compatible_without_industry_terms():
    # Old-style profile (applications with no industry_terms) still works.
    from .fakes import profile_json

    text = profile_json(
        problem=("p", "reducing inter-chip energy per bit"),
        solution=("s", "micro-ring modulator array coupled to a silicon waveguide"),
        applications=[("a", "photonic interconnect")],
        query_terms=["optical interconnect", "photonics"],
    )
    profile = build_profile(synthetic_patent_bundle().asset, FakeProvider(text))
    assert profile.query_terms == ["optical interconnect", "photonics"]
    assert profile.technology_summary == ""


def test_decomposition_persists(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())
    row = get_profile(session, asset.id)
    assert row.technology_summary
    assert row.candidate_applications and len(row.candidate_applications) == 3
    first = row.candidate_applications[0]
    assert first["application"] == "Data-centre optical interconnects"
    assert "co-packaged optics" in first["industry_terms"]
    assert first["end_customer"] == "hyperscale data centres"
