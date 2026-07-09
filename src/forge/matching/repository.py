"""Persistence for need-matching outputs (T11)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..db.models import Asset, NeedHypothesis
from .need_hypothesis import NeedHypothesisDraft


def save_need_hypotheses(
    session: Session, asset: Asset, drafts: list[NeedHypothesisDraft]
) -> list[NeedHypothesis]:
    """Replace an asset's need hypotheses with ``drafts`` (idempotent re-generation)."""
    session.execute(delete(NeedHypothesis).where(NeedHypothesis.asset_id == asset.id))
    rows: list[NeedHypothesis] = []
    for d in drafts:
        row = NeedHypothesis(
            asset=asset,
            company_id=d.company_id,
            hypothesised_need=d.hypothesised_need,
            track=d.track,
            strength=d.strength,
            evidence=d.evidence,
            rationale=d.rationale,
            model=d.model,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


def get_need_hypotheses(session: Session, asset_id: uuid.UUID) -> list[NeedHypothesis]:
    """An asset's need hypotheses, strongest first, with the company loaded."""
    stmt = (
        select(NeedHypothesis)
        .where(NeedHypothesis.asset_id == asset_id)
        .options(selectinload(NeedHypothesis.company))
        .order_by(NeedHypothesis.track, NeedHypothesis.created_at)
    )
    return list(session.execute(stmt).scalars())
