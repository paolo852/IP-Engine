"""L5 quarterly recalibration loop + audit log.

Reads the committee's decisions and the realised outcomes (slice 9) and asks one
transparent question: did the Engine's ventureability score actually separate
winners (spun-out / licensed) from losers (parked / abandoned)? It reports the
separation, proposes a pursue-cutoff, and logs every run for audit.

It only PROPOSES. There is no black-box learning here — just documented
separation statistics. Humans decide whether to retune the weights/thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import RecalibrationConfig, ScoringConfig
from .db.models import CommitteeDecision, RecalibrationLog


@dataclass
class RecalibrationResult:
    run_at: datetime
    since: datetime | None
    sample_size: int
    good_count: int
    bad_count: int
    mean_score_good: float | None
    mean_score_bad: float | None
    separation: float | None
    recommended_cutoff: float | None
    verdict: str  # "well_calibrated" | "needs_review" | "insufficient_data"
    notes: str
    weights_snapshot: dict
    id: object | None = None

    def summary(self) -> str:
        return (
            f"recalibration [{self.verdict}] on {self.sample_size} assets "
            f"({self.good_count} good / {self.bad_count} bad): {self.notes}"
        )


def _latest_per_asset(session: Session, model, time_col):
    out: dict = {}
    for row in session.execute(select(model).order_by(time_col.desc(), model.id.desc())).scalars():
        out.setdefault(row.asset_id, row)
    return out


def run_recalibration(
    session: Session,
    *,
    scoring_config: ScoringConfig,
    config: RecalibrationConfig,
    since: datetime | None = None,
    persist: bool = True,
) -> RecalibrationResult:
    """Assess Engine-score calibration against realised outcomes; log the run."""
    from .db.models import AssetOutcome  # local import keeps module import light

    decisions = _latest_per_asset(session, CommitteeDecision, CommitteeDecision.decided_at)
    outcomes = _latest_per_asset(session, AssetOutcome, AssetOutcome.recorded_at)

    good: list[float] = []
    bad: list[float] = []
    for asset_id, outcome in outcomes.items():
        if since is not None and outcome.recorded_at < since:
            continue
        decision = decisions.get(asset_id)
        if decision is None or decision.engine_score is None:
            continue
        value = outcome.outcome.value
        if value in config.good_outcomes:
            good.append(decision.engine_score)
        elif value in config.bad_outcomes:
            bad.append(decision.engine_score)

    sample = len(good) + len(bad)
    mean_good = mean(good) if good else None
    mean_bad = mean(bad) if bad else None
    separation = (
        mean_good - mean_bad if (mean_good is not None and mean_bad is not None) else None
    )
    cutoff = (mean_good + mean_bad) / 2 if separation is not None else None

    if sample < config.min_sample:
        verdict = "insufficient_data"
        notes = f"only {sample} decided+realised assets (need {config.min_sample})"
    elif separation is None:
        verdict = "insufficient_data"
        notes = "need both good and bad realised outcomes to assess separation"
    elif separation >= config.min_separation:
        verdict = "well_calibrated"
        notes = (
            f"score separates winners from losers by {separation:+.2f}; "
            f"suggested pursue-cutoff ~{cutoff:.2f}"
        )
    else:
        verdict = "needs_review"
        notes = (
            f"score barely separates outcomes ({separation:+.2f} < "
            f"{config.min_separation}); review dimension weights"
        )

    if verdict == "insufficient_data":
        cutoff = None  # don't propose a pursue-cutoff we can't support

    result = RecalibrationResult(
        run_at=datetime.now(timezone.utc),
        since=since,
        sample_size=sample,
        good_count=len(good),
        bad_count=len(bad),
        mean_score_good=mean_good,
        mean_score_bad=mean_bad,
        separation=separation,
        recommended_cutoff=cutoff,
        verdict=verdict,
        notes=notes,
        weights_snapshot=dict(scoring_config.weights),
    )

    if persist:
        row = RecalibrationLog(
            run_at=result.run_at,
            since=since,
            sample_size=sample,
            good_count=len(good),
            bad_count=len(bad),
            mean_score_good=mean_good,
            mean_score_bad=mean_bad,
            separation=separation,
            recommended_cutoff=cutoff,
            verdict=verdict,
            notes=notes,
            weights_snapshot=result.weights_snapshot,
        )
        session.add(row)
        session.commit()
        result.id = row.id

    return result


def get_recalibration_logs(session: Session) -> list[RecalibrationLog]:
    """Return recalibration log rows, newest first (the recalibration history)."""
    return list(
        session.execute(
            select(RecalibrationLog).order_by(RecalibrationLog.run_at.desc())
        ).scalars()
    )
