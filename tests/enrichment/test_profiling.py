"""LLM profiling service: structure, grounding verification, and edge cases."""

from __future__ import annotations

import pytest

from forge.db.models import Asset, AssetType
from forge.enrichment import GroundingError, ProfilingError, build_profile
from forge.enrichment.profiling import PROFILE_JSON_SCHEMA

from .fakes import FakeProvider, profile_json

# Quotes below are verbatim substrings of the asset text built in `asset()`.
ABSTRACT = (
    "A photonic interconnect architecture reducing inter-chip energy per bit "
    "for edge inference workloads."
)
CLAIMS = (
    "1. An interconnect comprising a micro-ring modulator array coupled to a "
    "silicon waveguide."
)
TITLE = "Low-power photonic interconnect for edge AI accelerators"


def asset() -> Asset:
    return Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title=TITLE,
        abstract=ABSTRACT,
        claims_or_description=CLAIMS,
    )


def grounded_response() -> str:
    return profile_json(
        problem=("High energy per bit in edge-AI interconnects",
                 "reducing inter-chip energy per bit for edge inference workloads"),
        solution=("Micro-ring modulator photonic interconnect",
                  "a micro-ring modulator array coupled to a silicon waveguide"),
        applications=[("Edge AI accelerators", "photonic interconnect for edge AI accelerators")],
        query_terms=["optical interconnect energy efficiency", "edge inference hardware"],
    )


def test_build_profile_grounds_each_statement_to_a_source_field():
    provider = FakeProvider(grounded_response())
    profile = build_profile(asset(), provider)

    assert profile.problem.source_field == "abstract"
    assert profile.solution.source_field == "claims_or_description"
    assert profile.applications[0].source_field == "title"
    assert profile.query_terms[0] == "optical interconnect energy efficiency"
    assert profile.model == "fake-model"


def test_provider_is_asked_for_schema_constrained_json():
    provider = FakeProvider(grounded_response())
    build_profile(asset(), provider)
    assert provider.calls[0]["json_schema"] == PROFILE_JSON_SCHEMA
    # The asset text is handed over as data inside the user message.
    assert "micro-ring modulator" in provider.calls[0]["user"]


def test_ungrounded_quote_is_rejected():
    bad = profile_json(
        problem=("Something", "reducing inter-chip energy per bit for edge inference workloads"),
        solution=("Fabricated", "teleportation via blockchain quantum entanglement"),  # not in source
        applications=[],
        query_terms=[],
    )
    with pytest.raises(GroundingError, match="solution"):
        build_profile(asset(), FakeProvider(bad))


def test_quote_matching_tolerates_whitespace_and_case():
    # Same words as the abstract quote but re-spaced / re-cased.
    weird = profile_json(
        problem=("p", "Reducing   Inter-Chip  Energy Per Bit"),
        solution=("s", "micro-ring modulator array"),
        applications=[],
        query_terms=[],
    )
    profile = build_profile(asset(), FakeProvider(weird))
    assert profile.problem.source_field == "abstract"


def test_empty_asset_cannot_be_profiled():
    bare = Asset(asset_type=AssetType.patent, source_layer="L1.synthetic")
    with pytest.raises(ProfilingError, match="no title/abstract/claims"):
        build_profile(bare, FakeProvider("{}"))


def test_malformed_model_json_raises_profiling_error():
    with pytest.raises(ProfilingError, match="valid JSON"):
        build_profile(asset(), FakeProvider("this is not json"))


def test_missing_quote_field_raises_profiling_error():
    import json

    payload = json.dumps(
        {"problem": {"value": "x"}, "solution": {"value": "y", "quote": "z"},
         "applications": [], "query_terms": []}
    )
    with pytest.raises(ProfilingError, match="'value' and 'quote'"):
        build_profile(asset(), FakeProvider(payload))


def test_verification_can_be_skipped():
    # With verify=False, an unverifiable quote does not raise (source_field stays None).
    bad = profile_json(
        problem=("p", "not in the source text at all"),
        solution=("s", "also absent"),
        applications=[],
        query_terms=[],
    )
    profile = build_profile(asset(), FakeProvider(bad), verify=False)
    assert profile.problem.source_field is None
