"""L5 decision/outcome capture + the committee dashboard read model."""

from __future__ import annotations

from dataclasses import dataclass

from forge.db.models import DecisionType, OutcomeType
from forge.output.decisions import capture_decision, capture_outcome, dashboard
from forge.repository import latest_decision, latest_outcome, save_asset

from .synthetic.assets import minimal_grounded_bundle, synthetic_patent_bundle


@dataclass
class FakeScore:
    value: float
    coverage: float


@dataclass
class FakeRouting:
    value: str


@dataclass
class FakeCorroboration:
    routing: FakeRouting


def test_decision_snapshots_engine_recommendation(session):
    asset = save_asset(session, synthetic_patent_bundle())

    dec = capture_decision(
        session, asset,
        decision=DecisionType.sprint, decided_by="committee@org",
        score=FakeScore(0.85, 0.75),
        corroboration=FakeCorroboration(FakeRouting("sprint")),
        rationale="strong corroboration across streams",
    )
    session.expunge_all()

    loaded = latest_decision(session, asset.id)
    assert loaded.decision is DecisionType.sprint
    assert loaded.engine_score == 0.85
    assert loaded.engine_coverage == 0.75
    assert loaded.engine_routing == "sprint"
    assert loaded.decided_by == "committee@org"


def test_outcome_links_to_decision_and_round_trips(session):
    asset = save_asset(session, synthetic_patent_bundle())
    dec = capture_decision(session, asset, decision=DecisionType.license, decided_by="c")

    capture_outcome(
        session, asset, outcome=OutcomeType.licensed, recorded_by="ops@org",
        notes="licensed to Acme", decision=dec,
    )
    session.expunge_all()

    out = latest_outcome(session, asset.id)
    assert out.outcome is OutcomeType.licensed
    assert out.notes == "licensed to Acme"
    assert out.decision_id == dec.id


def test_latest_decision_wins(session):
    asset = save_asset(session, synthetic_patent_bundle())
    capture_decision(session, asset, decision=DecisionType.hold, decided_by="c1")
    capture_decision(session, asset, decision=DecisionType.sprint, decided_by="c2")
    assert latest_decision(session, asset.id).decision is DecisionType.sprint


def test_dashboard_ranks_by_score_with_unreviewed_last(session):
    a_hi = save_asset(session, synthetic_patent_bundle())
    a_lo = save_asset(session, minimal_grounded_bundle())  # title "Synthetic soil-moisture..."
    a_pending = save_asset(session, minimal_grounded_bundle())

    capture_decision(session, a_hi, decision=DecisionType.sprint, decided_by="c",
                     score=FakeScore(0.85, 0.75), corroboration=FakeCorroboration(FakeRouting("sprint")))
    capture_decision(session, a_lo, decision=DecisionType.park, decided_by="c",
                     score=FakeScore(0.30, 0.75), corroboration=FakeCorroboration(FakeRouting("park")))
    capture_outcome(session, a_hi, outcome=OutcomeType.in_progress, recorded_by="ops")
    session.expunge_all()

    rows = dashboard(session)
    assert len(rows) == 3
    # Highest score first, then lower, then the unreviewed (no score) last.
    assert rows[0].asset_id == a_hi.id and rows[0].engine_score == 0.85
    assert rows[0].decision == "sprint" and rows[0].outcome == "in_progress"
    assert rows[1].asset_id == a_lo.id and rows[1].decision == "park"
    assert rows[2].engine_score is None and rows[2].reviewed is False


def test_dashboard_empty_when_no_assets(session):
    assert dashboard(session) == []
