"""Asset persistence with the grounding rule enforced at the seam.

``save_asset`` is the only sanctioned way to persist an asset. It refuses to
commit a factual field that has no provenance, so "no source -> no claim" holds
by construction. ``get_asset`` round-trips it back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db.models import (
    Asset,
    AssetProfile,
    Evidence,
    FieldProvenance,
    Licence,
    ProfileGrounding,
    Source,
)


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


def save_profile(session: Session, asset: Asset, profile) -> AssetProfile:
    """Persist a grounded AssetProfile, refusing any ungrounded statement.

    ``profile`` is a ``forge.enrichment.AssetProfile``. Every grounded statement
    must carry a located ``source_field`` (set by verification) — otherwise this
    raises GroundingError and commits nothing, keeping "no source -> no claim"
    true at the persistence seam too.
    """
    from .enrichment.profiling import GroundingError  # local import avoids cycle

    grounded = profile.grounded_fields()
    missing = [gf.name for gf in grounded if gf.source_field is None]
    if missing:
        raise GroundingError(
            "refusing to persist ungrounded profile statements: " + ", ".join(missing)
        )

    # The LLM enrichment act is itself a Source (a derived, internal-licence
    # signal — never licensed raw data).
    source = Source(
        source_type="llm:profiling",
        licence=Licence.internal,
        locator=f"{profile.model}/{profile.prompt_version}",
        retrieved_at=datetime.now(timezone.utc),
    )
    row = AssetProfile(
        asset=asset,
        source=source,
        problem=profile.problem.value,
        solution=profile.solution.value,
        applications=[a.value for a in profile.applications],
        query_terms=list(profile.query_terms),
        model=profile.model,
        prompt_version=profile.prompt_version,
    )
    for gf in grounded:
        row.grounding.append(
            ProfileGrounding(
                field_name=gf.name,
                supporting_quote=gf.quote,
                source_field=gf.source_field,
            )
        )

    session.add(source)
    session.add(row)
    session.commit()
    return row


def get_profile(session: Session, asset_id: uuid.UUID) -> AssetProfile | None:
    """Load an asset's profile with its grounding and source attached."""
    stmt = (
        select(AssetProfile)
        .where(AssetProfile.asset_id == asset_id)
        .options(
            selectinload(AssetProfile.grounding),
            selectinload(AssetProfile.source),
        )
    )
    return session.execute(stmt).scalar_one_or_none()
