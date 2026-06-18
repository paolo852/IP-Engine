"""Deleting an asset removes it and everything derived from it, RBAC-gated."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from forge.db.base import make_session_factory
from forge.db.models import (
    AssetScore,
    AssetSynthesis,
    CommitteeDecision,
    DecisionType,
    Evidence,
    FieldProvenance,
    Source,
)
from forge.output.decisions import capture_decision
from forge.repository import (
    delete_asset,
    get_asset,
    save_asset,
    save_score,
)
from forge.scoring import DimensionScore, VentureabilityScore
from forge.seed import OfflineProfilingProvider
from forge.web import create_app

from .synthetic.assets import synthetic_patent_bundle

AS_OF = date(2026, 6, 18)


@pytest.fixture()
def client(engine):
    return TestClient(create_app(session_factory=make_session_factory(engine)))


def _score():
    dims = [DimensionScore("market_pull", 0.4, "x")]
    return VentureabilityScore(0.5, 0.6, dims, {"market_pull": 1.0})


def test_delete_cascades_all_derived_data(session):
    from forge.pipeline import Pipeline, PipelineConfig

    asset = save_asset(session, synthetic_patent_bundle())
    # Build derived rows: full pipeline (profile/evidence/score) + a decision.
    Pipeline(PipelineConfig.from_files(as_of=AS_OF), OfflineProfilingProvider()).run(
        session, [asset.id]
    )
    capture_decision(session, asset, decision=DecisionType.sprint, decided_by="c",
                     score=_score())
    assert session.query(Evidence).filter_by(asset_id=asset.id).count() > 0
    assert session.query(AssetScore).filter_by(asset_id=asset.id).count() == 1

    assert delete_asset(session, asset.id) is True

    assert get_asset(session, asset.id) is None
    for model in (Evidence, FieldProvenance, AssetScore, AssetSynthesis, CommitteeDecision):
        assert session.query(model).filter_by(asset_id=asset.id).count() == 0
    # No orphaned sources left behind.
    assert session.query(Source).count() == 0


def test_delete_missing_returns_false(session):
    import uuid

    assert delete_asset(session, uuid.uuid4()) is False


def test_web_admin_can_delete(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "admin")
    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _score(), routing="sprint")
    asset_id = asset.id  # capture before the row is deleted

    r = client.post(f"/asset/{asset_id}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    session.expire_all()
    assert get_asset(session, asset_id) is None


def test_web_viewer_cannot_delete(client, session, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "viewer")
    asset = save_asset(session, synthetic_patent_bundle())
    r = client.post(f"/asset/{asset.id}/delete", follow_redirects=False)
    assert r.status_code == 403
    session.expire_all()
    assert get_asset(session, asset.id) is not None  # still there


def test_detail_shows_delete_only_for_authorised(client, session, monkeypatch):
    asset = save_asset(session, synthetic_patent_bundle())
    monkeypatch.setenv("FORGE_ROLE", "admin")
    assert "Delete asset" in client.get(f"/asset/{asset.id}").text
    monkeypatch.setenv("FORGE_ROLE", "viewer")
    assert "Delete asset" not in client.get(f"/asset/{asset.id}").text


def test_admin_role_implies_delete_permission():
    from forge.config import load_governance_config
    from forge.governance import permissions_for

    gov = load_governance_config("config/governance.yaml")
    assert "delete_asset" in permissions_for("admin", gov)
    assert "delete_asset" not in permissions_for("viewer", gov)
