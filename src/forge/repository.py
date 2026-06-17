"""Asset persistence with the grounding rule enforced at the seam.

``save_asset`` is the only sanctioned way to persist an asset. It refuses to
commit a factual field that has no provenance, so "no source -> no claim" holds
by construction. ``get_asset`` round-trips it back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db.models import Asset, Evidence, FieldProvenance, Source


class GroundingError(ValueError):
    """Raised when a populated factual field lacks any provenance (rule 1)."""


@dataclass
class ProvenanceEntry:
    """One (field -> source) grounding link to attach to an asset."""

    field_name: str
    source: Source
    note: str | None = None


@dataclass
class AssetBundle:
    """An asset together with the provenance (and optional evidence) that grounds it."""

    asset: Asset
    provenance: list[ProvenanceEntry] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def ungrounded_fields(asset: Asset, grounded_field_names: set[str]) -> list[str]:
    """Populated factual fields that have no provenance among ``grounded_field_names``."""
    return [
        name
        for name in asset.populated_groundable_fields()
        if name not in grounded_field_names
    ]


def save_asset(session: Session, bundle: AssetBundle) -> Asset:
    """Persist an asset + its provenance, enforcing the grounding rule.

    Every populated factual field MUST be covered by at least one ProvenanceEntry,
    otherwise ``GroundingError`` is raised and nothing is committed.
    """
    grounded = {entry.field_name for entry in bundle.provenance}
    missing = ungrounded_fields(bundle.asset, grounded)
    if missing:
        raise GroundingError(
            "ungrounded factual fields (no source -> no claim): " + ", ".join(missing)
        )

    asset = bundle.asset
    session.add(asset)

    for entry in bundle.provenance:
        session.add(entry.source)
        session.add(
            FieldProvenance(
                asset=asset,
                source=entry.source,
                field_name=entry.field_name,
                note=entry.note,
            )
        )

    for ev in bundle.evidence:
        if ev.source is not None:
            session.add(ev.source)
        ev.asset = asset
        session.add(ev)

    session.commit()
    return asset


def get_asset(session: Session, asset_id: uuid.UUID) -> Asset | None:
    """Load an asset with its provenance and evidence eagerly attached."""
    stmt = (
        select(Asset)
        .where(Asset.id == asset_id)
        .options(
            selectinload(Asset.provenance).selectinload(FieldProvenance.source),
            selectinload(Asset.evidence),
        )
    )
    return session.execute(stmt).scalar_one_or_none()


def provenance_map(asset: Asset) -> dict[str, list[Source]]:
    """Field name -> the source records that ground it (for briefs/audit)."""
    out: dict[str, list[Source]] = {}
    for link in asset.provenance:
        out.setdefault(link.field_name, []).append(link.source)
    return out
