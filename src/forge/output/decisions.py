"""Decision/outcome capture + the committee dashboard read model (L5).

The committee reviews a brief and records a decision; the realised outcome is
recorded later. Both are governance inputs (who + when), not Engine claims, and
they snapshot the Engine's recommendation so the quarterly recalibration loop
(slice 10) can compare Engine signal vs human decision vs outcome.

``dashboard`` is the ranked pipeline view a UI renders: every asset with its
latest decision/outcome and the score that informed it, ordered by ventureability.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Asset,
    AssetOutcome,
    AssetScore,
    CommitteeDecision,
    DecisionType,
    OutcomeType,
)
from ..repository import record_decision, record_outcome

__all__ = [
    "DecisionType",
    "OutcomeType",
    "DashboardRow",
    "capture_decision",
    "capture_outcome",
    "dashboard",
]


def capture_decision(
    session: Session,
    asset: Asset,
    *,
    decision: DecisionType,
    decided_by: str,
    score=None,  # forge.scoring.VentureabilityScore
    corroboration=None,  # forge.streams.corroboration.Corroboration
    rationale: str | None = None,
) -> CommitteeDecision:
    """Record a decision, snapshotting the Engine's score/routing that informed it."""
    return record_decision(
        session,
        asset,
        decision=decision,
        decided_by=decided_by,
        rationale=rationale,
        engine_routing=corroboration.routing.value if corroboration is not None else None,
        engine_score=score.value if score is not None else None,
        engine_coverage=score.coverage if score is not None else None,
    )


def capture_outcome(
    session: Session,
    asset: Asset,
    *,
    outcome: OutcomeType,
    recorded_by: str,
    notes: str | None = None,
    decision: CommitteeDecision | None = None,
) -> AssetOutcome:
    return record_outcome(
        session, asset, outcome=outcome, recorded_by=recorded_by, notes=notes, decision=decision
    )


@dataclass
class DashboardRow:
    asset_id: object
    title: str | None
    asset_type: str
    engine_score: float | None
    engine_routing: str | None
    decision: str | None
    decided_by: str | None
    outcome: str | None

    @property
    def reviewed(self) -> bool:
        return self.decision is not None


def dashboard(session: Session) -> list[DashboardRow]:
    """Ranked pipeline: every asset with its latest decision/outcome + score.

    The displayed score prefers the latest persisted engine score (AssetScore,
    written by the pipeline) and falls back to the decision-time snapshot when an
    asset has been reviewed but not (re-)scored. Sorted by ventureability
    descending; assets without any score sort last, then by title.
    """
    assets = list(session.execute(select(Asset)).scalars())

    latest_dec: dict = {}
    for d in session.execute(
        select(CommitteeDecision).order_by(
            CommitteeDecision.decided_at.desc(), CommitteeDecision.id.desc()
        )
    ).scalars():
        latest_dec.setdefault(d.asset_id, d)

    latest_out: dict = {}
    for o in session.execute(
        select(AssetOutcome).order_by(
            AssetOutcome.recorded_at.desc(), AssetOutcome.id.desc()
        )
    ).scalars():
        latest_out.setdefault(o.asset_id, o)

    scores: dict = {
        s.asset_id: s for s in session.execute(select(AssetScore)).scalars()
    }

    rows: list[DashboardRow] = []
    for asset in assets:
        dec = latest_dec.get(asset.id)
        out = latest_out.get(asset.id)
        sc = scores.get(asset.id)
        engine_score = sc.ventureability if sc else (dec.engine_score if dec else None)
        engine_routing = sc.routing if sc else (dec.engine_routing if dec else None)
        rows.append(
            DashboardRow(
                asset_id=asset.id,
                title=asset.title,
                asset_type=asset.asset_type.value,
                engine_score=engine_score,
                engine_routing=engine_routing,
                decision=dec.decision.value if dec else None,
                decided_by=dec.decided_by if dec else None,
                outcome=out.outcome.value if out else None,
            )
        )

    rows.sort(
        key=lambda r: (
            r.engine_score is None,
            -(r.engine_score or 0.0),
            (r.title or "").lower(),
        )
    )
    return rows
