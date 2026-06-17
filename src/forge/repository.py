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
    AssetOutcome,
    AssetProfile,
    CommitteeDecision,
    DecisionType,
    Evidence,
    FieldProvenance,
    Licence,
    OutcomeType,
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


def save_stream_result(session: Session, asset: Asset, result) -> list[Evidence]:
    """Persist a cross-referencing StreamResult's findings as Evidence rows.

    ``result`` is a ``forge.streams.StreamResult``. Each EvidenceRecord becomes
    one Evidence row backed by its own Source — derived signals, separable from
    licensed raw data (rule 5), each carrying provenance.
    """
    rows: list[Evidence] = []
    for rec in result.evidence():
        source = Source(
            source_type=rec.source.source_type,
            licence=rec.source.licence,
            locator=rec.source.locator,
            retrieved_at=datetime.now(timezone.utc),
        )
        evidence = Evidence(
            asset=asset,
            source=source,
            stream=rec.stream,
            observed_at=rec.observed_at,
            match_strength=rec.match_strength,
            snippet=rec.snippet,
            link=rec.link,
        )
        session.add(source)
        session.add(evidence)
        rows.append(evidence)
    session.commit()
    return rows


def get_evidence(
    session: Session, asset_id: uuid.UUID, *, stream: str | None = None
) -> list[Evidence]:
    """Load an asset's evidence rows (optionally filtered to one stream)."""
    stmt = (
        select(Evidence)
        .where(Evidence.asset_id == asset_id)
        .options(selectinload(Evidence.source))
        .order_by(Evidence.created_at)
    )
    if stream is not None:
        stmt = stmt.where(Evidence.stream == stream)
    return list(session.execute(stmt).scalars())


# -- L5 decision / outcome capture ------------------------------------------
def record_decision(
    session: Session,
    asset: Asset,
    *,
    decision: DecisionType,
    decided_by: str,
    rationale: str | None = None,
    engine_routing: str | None = None,
    engine_score: float | None = None,
    engine_coverage: float | None = None,
) -> CommitteeDecision:
    """Persist the committee's decision with the Engine's recommendation snapshot."""
    row = CommitteeDecision(
        asset=asset,
        decision=decision,
        decided_by=decided_by,
        rationale=rationale,
        engine_routing=engine_routing,
        engine_score=engine_score,
        engine_coverage=engine_coverage,
    )
    session.add(row)
    session.commit()
    return row


def record_outcome(
    session: Session,
    asset: Asset,
    *,
    outcome: OutcomeType,
    recorded_by: str,
    notes: str | None = None,
    decision: CommitteeDecision | None = None,
) -> AssetOutcome:
    """Persist a realised outcome for an asset (optionally linked to a decision)."""
    row = AssetOutcome(
        asset=asset,
        outcome=outcome,
        recorded_by=recorded_by,
        notes=notes,
        decision=decision,
    )
    session.add(row)
    session.commit()
    return row


def latest_decision(session: Session, asset_id: uuid.UUID) -> CommitteeDecision | None:
    stmt = (
        select(CommitteeDecision)
        .where(CommitteeDecision.asset_id == asset_id)
        .order_by(CommitteeDecision.decided_at.desc(), CommitteeDecision.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def latest_outcome(session: Session, asset_id: uuid.UUID) -> AssetOutcome | None:
    stmt = (
        select(AssetOutcome)
        .where(AssetOutcome.asset_id == asset_id)
        .order_by(AssetOutcome.recorded_at.desc(), AssetOutcome.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
