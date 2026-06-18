"""Persistence of the latest engine ventureability score (AssetScore).

The pipeline writes one score row per asset so the dashboard and clustering can
rank on live engine output without re-running. Re-scoring replaces in place
(idempotent), and the dashboard prefers the persisted score over the
decision-time snapshot.
"""

from __future__ import annotations

from forge.db.models import AssetScore, DecisionType
from forge.output.decisions import capture_decision, dashboard
from forge.repository import delete_score, get_score, save_asset, save_score
from forge.scoring import DimensionScore, VentureabilityScore

from .synthetic.assets import synthetic_patent_bundle


def _score(value, coverage=0.75):
    dims = [
        DimensionScore("technology_maturity", 0.5, "application/pending"),
        DimensionScore("capital_intensity", None, "no cost data"),
    ]
    return VentureabilityScore(value, coverage, dims, {"technology_maturity": 1.0,
                                                       "capital_intensity": 1.0})


def test_save_score_persists_dimensions_and_routing(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _score(0.62), routing="sprint")

    row = get_score(session, asset.id)
    assert row is not None
    assert row.ventureability == 0.62
    assert row.coverage == 0.75
    assert row.routing == "sprint"
    # The explainable breakdown is stored verbatim, indeterminate value included.
    by_dim = {d["dimension"]: d for d in row.dimensions}
    assert by_dim["technology_maturity"]["value"] == 0.5
    assert by_dim["capital_intensity"]["value"] is None
    assert "no cost data" in by_dim["capital_intensity"]["rationale"]


def test_save_score_is_idempotent(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _score(0.40), routing="watch")
    save_score(session, asset, _score(0.80), routing="sprint")

    # Exactly one row per asset; the latest replaces the previous.
    rows = session.query(AssetScore).filter(AssetScore.asset_id == asset.id).all()
    assert len(rows) == 1
    assert rows[0].ventureability == 0.80
    assert rows[0].routing == "sprint"


def test_indeterminate_overall_score_persists(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _score(None, coverage=0.0))
    row = get_score(session, asset.id)
    assert row is not None and row.ventureability is None and row.coverage == 0.0


def test_delete_score_removes_row(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_score(session, asset, _score(0.5))
    delete_score(session, asset.id)
    assert get_score(session, asset.id) is None


def test_dashboard_prefers_persisted_score_over_snapshot(session):
    asset = save_asset(session, synthetic_patent_bundle())

    class _Snap:
        value, coverage = 0.30, 0.5

    # Decision captured an older snapshot of 0.30 ...
    capture_decision(session, asset, decision=DecisionType.hold,
                     decided_by="c", score=_Snap())
    # ... but the live engine score is 0.85.
    save_score(session, asset, _score(0.85), routing="sprint")

    row = next(r for r in dashboard(session) if r.asset_id == asset.id)
    assert row.engine_score == 0.85
    assert row.engine_routing == "sprint"
    assert row.decision == "hold"  # the human decision is unchanged


def test_dashboard_falls_back_to_snapshot_when_unscored(session):
    asset = save_asset(session, synthetic_patent_bundle())

    class _Snap:
        value, coverage = 0.42, 0.5

    capture_decision(session, asset, decision=DecisionType.sprint,
                     decided_by="c", score=_Snap())
    row = next(r for r in dashboard(session) if r.asset_id == asset.id)
    assert row.engine_score == 0.42
