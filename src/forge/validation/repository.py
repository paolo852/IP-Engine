"""Capture + read the two human validations that feed two-axis routing (T13).

The NEED axis comes from the company (need_validation); the TRL axis comes from
the inventor (inventor_trl_check). Both are append-only histories — the latest
record per key is authoritative. Nothing here decides routing; it only records
what humans reported (rule 4 for needs, rule 5 for TRL).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Asset,
    InventorTrlCheck,
    NeedOutcome,
    NeedValidation,
    Track,
)


# -- need validation (company / NEED axis) ----------------------------------
def record_need_validation(
    session: Session,
    asset: Asset,
    *,
    company_id: uuid.UUID,
    track: Track,
    outcome: NeedOutcome,
    validated_by: str,
    note: str | None = None,
) -> NeedValidation:
    row = NeedValidation(
        asset=asset,
        company_id=company_id,
        track=track,
        outcome=outcome,
        validated_by=validated_by,
        note=note,
    )
    session.add(row)
    session.commit()
    return row


def latest_need_validation(
    session: Session, asset_id: uuid.UUID, company_id: uuid.UUID, track: Track
) -> NeedValidation | None:
    stmt = (
        select(NeedValidation)
        .where(
            NeedValidation.asset_id == asset_id,
            NeedValidation.company_id == company_id,
            NeedValidation.track == track,
        )
        .order_by(NeedValidation.recorded_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def has_any_need_validation(session: Session, asset_id: uuid.UUID) -> bool:
    """Whether ANY need validation exists for the asset (routing gate: the NEED
    axis is only decidable once a company has responded at all)."""
    stmt = select(NeedValidation.id).where(NeedValidation.asset_id == asset_id).limit(1)
    return session.execute(stmt).first() is not None


def confirmed_tracks(session: Session, asset_id: uuid.UUID) -> set[Track]:
    """Tracks with a latest ``need_confirmed`` validation (any company).

    The latest record per (company, track) is authoritative, so a later denial
    overrides an earlier confirmation. This is the raw NEED-axis input routing
    (T14) crosses with the TRL axis — it does not itself decide.
    """
    stmt = (
        select(NeedValidation)
        .where(NeedValidation.asset_id == asset_id)
        .order_by(NeedValidation.recorded_at.desc())
    )
    seen: set[tuple[uuid.UUID, Track]] = set()
    confirmed: set[Track] = set()
    for v in session.execute(stmt).scalars():
        key = (v.company_id, v.track)
        if key in seen:
            continue  # older than the latest for this (company, track)
        seen.add(key)
        if v.outcome is NeedOutcome.need_confirmed:
            confirmed.add(v.track)
    return confirmed


# -- inventor TRL check (TRL axis) ------------------------------------------
def record_trl_check(
    session: Session,
    asset: Asset,
    *,
    trl_band: str,
    evidence: dict | None = None,
    recorded_by: str,
    note: str | None = None,
) -> InventorTrlCheck:
    row = InventorTrlCheck(
        asset=asset,
        trl_band=trl_band,
        evidence=evidence or {},
        recorded_by=recorded_by,
        note=note,
    )
    session.add(row)
    session.commit()
    return row


def latest_trl_check(session: Session, asset_id: uuid.UUID) -> InventorTrlCheck | None:
    stmt = (
        select(InventorTrlCheck)
        .where(InventorTrlCheck.asset_id == asset_id)
        .order_by(InventorTrlCheck.recorded_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()
