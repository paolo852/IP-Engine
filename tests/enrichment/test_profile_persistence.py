"""Persisting grounded profiles: round-trip + grounding enforced at the seam."""

from __future__ import annotations

import pytest

from forge.enrichment import GroundingError, build_profile
from forge.repository import get_profile, save_asset, save_profile

from ..synthetic.assets import synthetic_patent_bundle
from .fakes import FakeProvider, profile_json


def _grounded_response(asset):
    # Quotes are verbatim substrings of the synthetic patent's fields.
    return profile_json(
        problem=("Lapsing photonic interconnect IP",
                 "photonic interconnect architecture reducing inter-chip energy per bit"),
        solution=("Micro-ring modulator interconnect",
                  "micro-ring modulator array coupled to a silicon waveguide"),
        applications=[("Edge AI", "edge AI accelerators")],
        query_terms=["optical interconnect", "edge inference energy"],
    )


def test_profile_round_trips_with_grounding(session):
    bundle = synthetic_patent_bundle()
    asset = save_asset(session, bundle)

    profile = build_profile(asset, FakeProvider(_grounded_response(asset)))
    saved = save_profile(session, asset, profile)
    session.expunge_all()

    loaded = get_profile(session, asset.id)
    assert loaded is not None
    assert loaded.problem.startswith("Lapsing photonic")
    assert loaded.applications == ["Edge AI"]
    assert loaded.query_terms == ["optical interconnect", "edge inference energy"]
    # The enrichment is attributed to an internal-licence LLM source (rule 5).
    assert loaded.source.source_type == "llm:profiling"
    assert loaded.source.licence.value == "internal"
    # Every statement carries a grounding row pointing back to an asset field.
    by_field = {g.field_name: g for g in loaded.grounding}
    assert set(by_field) == {"problem", "solution", "application[0]"}
    assert by_field["solution"].source_field == "claims_or_description"
    assert by_field["application[0]"].source_field == "title"


def test_save_profile_refuses_ungrounded(session):
    bundle = synthetic_patent_bundle()
    asset = save_asset(session, bundle)

    profile = build_profile(asset, FakeProvider(_grounded_response(asset)))
    # Tamper: drop the verified source_field so the statement is now ungrounded.
    profile.problem.source_field = None

    with pytest.raises(GroundingError, match="problem"):
        save_profile(session, asset, profile)
    session.rollback()
    assert get_profile(session, asset.id) is None
