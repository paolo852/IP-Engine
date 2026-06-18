"""Quarterly recalibration loop: separation stats, verdict, and audit log."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forge.config import load_recalibration_config, load_scoring_config
from forge.db.models import DecisionType, OutcomeType
from forge.output.decisions import capture_decision, capture_outcome
from forge.recalibration import get_recalibration_logs, run_recalibration
from forge.repository import save_asset

from .synthetic.assets import minimal_grounded_bundle

CONFIG = load_recalibration_config("config/recalibration.yaml")
SCORING = load_scoring_config("config/scoring.yaml")


class _Score:
    def __init__(self, value):
        self.value, self.coverage = value, 0.75


def _decide(session, score, outcome, *, recorded_at=None):
    asset = save_asset(session, minimal_grounded_bundle())
    capture_decision(session, asset, decision=DecisionType.sprint, decided_by="c",
                     score=_Score(score))
    out = capture_outcome(session, asset, outcome=outcome, recorded_by="ops")
    if recorded_at is not None:
        out.recorded_at = recorded_at
        session.commit()
    return asset


def test_well_calibrated_when_score_separates_outcomes(session):
    # Winners scored high, losers scored low.
    _decide(session, 0.85, OutcomeType.spun_out)
    _decide(session, 0.80, OutcomeType.licensed)
    _decide(session, 0.20, OutcomeType.abandoned)
    _decide(session, 0.30, OutcomeType.parked)

    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG)
    assert result.verdict == "well_calibrated"
    assert result.sample_size == 4 and result.good_count == 2 and result.bad_count == 2
    assert result.separation is not None and result.separation > 0.4
    assert 0.4 < result.recommended_cutoff < 0.7
    assert result.weights_snapshot["market_pull"] == 0.25


def test_needs_review_when_score_does_not_separate(session):
    # Winners and losers scored about the same -> score isn't predictive.
    _decide(session, 0.55, OutcomeType.spun_out)
    _decide(session, 0.50, OutcomeType.licensed)
    _decide(session, 0.52, OutcomeType.abandoned)
    _decide(session, 0.49, OutcomeType.parked)

    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG)
    assert result.verdict == "needs_review"
    assert "review dimension weights" in result.notes


def test_insufficient_data_below_min_sample(session):
    _decide(session, 0.85, OutcomeType.spun_out)
    _decide(session, 0.20, OutcomeType.abandoned)
    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG)
    assert result.verdict == "insufficient_data"
    assert result.recommended_cutoff is None


def test_non_terminal_outcomes_are_excluded(session):
    _decide(session, 0.85, OutcomeType.spun_out)
    _decide(session, 0.80, OutcomeType.licensed)
    _decide(session, 0.70, OutcomeType.in_progress)  # not terminal -> ignored
    _decide(session, 0.20, OutcomeType.abandoned)
    _decide(session, 0.30, OutcomeType.parked)
    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG)
    assert result.sample_size == 4  # in_progress excluded


def test_since_filters_old_outcomes(session):
    old = datetime.now(timezone.utc) - timedelta(days=400)
    _decide(session, 0.85, OutcomeType.spun_out, recorded_at=old)
    _decide(session, 0.80, OutcomeType.licensed, recorded_at=old)
    _decide(session, 0.20, OutcomeType.abandoned)
    _decide(session, 0.30, OutcomeType.parked)

    since = datetime.now(timezone.utc) - timedelta(days=90)
    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG, since=since)
    # Only the two recent (bad) outcomes remain -> below sample, one group.
    assert result.good_count == 0 and result.bad_count == 2
    assert result.verdict == "insufficient_data"


def test_run_is_logged_for_audit(session):
    _decide(session, 0.85, OutcomeType.spun_out)
    _decide(session, 0.80, OutcomeType.licensed)
    _decide(session, 0.20, OutcomeType.abandoned)
    _decide(session, 0.30, OutcomeType.parked)
    result = run_recalibration(session, scoring_config=SCORING, config=CONFIG)

    logs = get_recalibration_logs(session)
    assert len(logs) == 1
    assert logs[0].id == result.id
    assert logs[0].verdict == "well_calibrated"
    assert logs[0].weights_snapshot["technology_maturity"] == 0.20


def test_persist_false_does_not_log(session):
    _decide(session, 0.85, OutcomeType.spun_out)
    run_recalibration(session, scoring_config=SCORING, config=CONFIG, persist=False)
    assert get_recalibration_logs(session) == []
