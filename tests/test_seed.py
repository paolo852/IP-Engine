"""Offline demo seeding: grounded profiles, persisted scores, idempotency."""

from __future__ import annotations

from datetime import date

from forge.enrichment.profiling import build_profile
from forge.repository import get_profile, get_score
from forge.seed import (
    OfflineProfilingProvider,
    seed_demo,
    synthetic_demo_bundles,
)

AS_OF = date(2026, 6, 18)


def test_offline_provider_grounds_every_statement():
    # The offline provider must satisfy the same grounding contract as the LLM:
    # each quote is a verbatim span of the asset's own text.
    provider = OfflineProfilingProvider()
    for bundle in synthetic_demo_bundles():
        profile = build_profile(bundle.asset, provider)  # raises if ungrounded
        assert profile.problem.source_field is not None
        assert profile.solution.source_field is not None
        for app in profile.applications:
            assert app.source_field is not None
        assert profile.query_terms  # query terms derived


def test_seed_demo_creates_scores_and_profiles(session):
    report = seed_demo(session, as_of=AS_OF)
    assert report.created == len(synthetic_demo_bundles())
    assert report.scored == report.created
    assert report.errors == []

    # Every seeded asset has a persisted, grounded profile and an engine score.
    from forge.db.models import Asset

    assets = session.query(Asset).all()
    assert len(assets) == report.created
    for asset in assets:
        assert get_profile(session, asset.id) is not None
        assert get_score(session, asset.id) is not None


def test_seed_demo_is_idempotent(session):
    first = seed_demo(session, as_of=AS_OF)
    assert first.created == len(synthetic_demo_bundles())
    second = seed_demo(session, as_of=AS_OF)
    assert second.created == 0
    assert second.skipped == len(synthetic_demo_bundles())


def test_seed_demo_respects_governance_policy(session):
    from forge.config import load_governance_config

    gov = load_governance_config("config/governance.yaml")
    # Synthetic assets are storable in development — seeding succeeds under policy.
    report = seed_demo(session, policy=gov, as_of=AS_OF)
    assert report.created == len(synthetic_demo_bundles())
    assert report.errors == []
