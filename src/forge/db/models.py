"""L2 unified asset schema with provenance per field.

Design notes (each ties to a non-negotiable rule):

* Grounding rule (1): ``Asset`` holds factual fields; ``FieldProvenance`` ties
  each populated factual field to a ``Source``. The repository layer refuses to
  persist a factual field that has no provenance, so "no source -> no claim" is
  enforced by construction rather than reviewer vigilance.
* Licence separation (5): ``Source`` records a ``licence`` and a ``raw_ref``
  *pointer* — never the licensed raw payload itself. Derived signals (``Evidence``)
  live in their own table and reference the source, so we can store/share derived
  signals without republishing licensed raw records.
* Config not code (3): no thresholds or weights live here; this is pure schema.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AssetType(str, enum.Enum):
    """Closed set of asset families the Engine ingests (per spec schema)."""

    patent = "patent"
    disclosure = "disclosure"
    software = "software"
    dataset = "dataset"
    thesis = "thesis"
    project_result = "project_result"


class Licence(str, enum.Enum):
    """Provenance licence class — drives licence separation (rule 5).

    ``licensed_*`` sources may only ever be referenced by a pointer; their raw
    payload must not be republished out of the Engine.
    """

    free = "free"  # e.g. EPO OPS, public web
    public = "public"  # open data, public registers
    internal = "internal"  # our organisation's own records
    synthetic = "synthetic"  # dev/test fixtures (no real data, rule 4)
    licensed_dealroom = "licensed_dealroom"
    licensed_patstat = "licensed_patstat"


# Asset fields that assert facts about the world and therefore REQUIRE grounding.
# Structural/bookkeeping columns (id, asset_type, source_layer, timestamps) are
# excluded: they describe the record, not a sourced claim.
GROUNDABLE_FIELDS: tuple[str, ...] = (
    "title",
    "abstract",
    "claims_or_description",
    "inventors",
    "owners",
    "co_owners",
    "legal_status",
    "key_dates",
    "fee_status",
    "encumbrances",
    "linked_publications",
    "classification_codes",
)


class Source(Base):
    """Where a piece of data came from. Anchor for the grounding rule."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    # e.g. "epo_ops", "patstat", "dealroom", "manual", "synthetic"
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    licence: Mapped[Licence] = mapped_column(
        Enum(Licence, name="licence"), nullable=False
    )
    # Stable locator for the origin (URI, accession id, file ref). For licensed
    # sources this is a POINTER only — never the raw payload (rule 5).
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional reference to where the raw payload is held (out-of-band store).
    # Deliberately a pointer/string, not the payload, to keep licensed raw data
    # separable from anything the Engine emits.
    raw_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    provenance: Mapped[list["FieldProvenance"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    def is_licensed(self) -> bool:
        return self.licence in (Licence.licensed_dealroom, Licence.licensed_patstat)


class Asset(Base):
    """A single intellectual asset — the L2 single source of truth.

    Array/struct fields use JSONB. Provenance for each populated factual field is
    held in ``field_provenance`` (one or more rows per field, allowing corroborating
    sources), not inline, so a field can be re-sourced without rewriting the asset.
    """

    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type"), nullable=False
    )
    # Origin layer/connector, e.g. "L1.epo_ops". Bookkeeping, not a sourced claim.
    source_layer: Mapped[str] = mapped_column(String(128), nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    claims_or_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    inventors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    owners: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    co_owners: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    legal_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_dates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fee_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encumbrances: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_publications: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Patent classification symbols (IPC/CPC), e.g. ["G02B 6/12", "H04B 10/00"].
    # A language-independent definition of the asset's field, used by S2 to size
    # the technical neighbourhood by class as well as by problem-space text.
    classification_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    provenance: Mapped[list["FieldProvenance"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="FieldProvenance.field_name",
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    def populated_groundable_fields(self) -> list[str]:
        """Factual fields that hold a (non-null, non-empty) value right now."""
        populated: list[str] = []
        for name in GROUNDABLE_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, (str, list, dict)) and len(value) == 0:
                continue
            populated.append(name)
        return populated


class FieldProvenance(Base):
    """Pointer from one Asset field to a Source — the grounding rule made physical.

    A field may have several rows (multiple corroborating sources). The unique
    constraint stops the same (asset, field, source) triple being recorded twice.
    """

    __tablename__ = "field_provenance"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "field_name", "source_id", name="uq_field_provenance"
        ),
        Index("ix_field_provenance_asset", "asset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    # The Asset attribute this provenance backs, e.g. "title" or "key_dates".
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship(back_populates="provenance")
    source: Mapped[Source] = relationship(back_populates="provenance")


class Evidence(Base):
    """A normalised, derived signal record (the common cross-stream shape).

    Streams S1–S4 (later slices) all reduce to this: source, date, match-strength,
    snippet, link. Kept in its own table to keep DERIVED signals separable from
    licensed raw data (rule 5) — this is the store the Engine may emit from.
    """

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "match_strength >= 0.0 AND match_strength <= 1.0",
            name="ck_evidence_match_strength_unit",
        ),
        Index("ix_evidence_asset", "asset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    # Which of the four streams produced this, e.g. "S2_patents". Free-text now;
    # constrained when streams land.
    stream: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    match_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship(back_populates="evidence")
    source: Mapped[Source] = relationship()


class AssetProfile(Base):
    """A grounded, structured profile derived by the L3 LLM profiling service.

    A DERIVED signal (rule 5): stored separately from raw asset text, attributed
    to an LLM-enrichment ``Source`` (licence=internal). The grounding for each
    statement lives in ``profile_grounding`` so a profile sentence is never
    emitted without a verbatim quote tying it back to a source field (rule 1).
    """

    __tablename__ = "asset_profile"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_asset_profile_asset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=False)
    applications: Mapped[list] = mapped_column(JSONB, nullable=False)
    query_terms: Mapped[list] = mapped_column(JSONB, nullable=False)
    technology_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{application, end_customer, use_case, industry_terms}] — the structured
    # market decomposition (E1). The market reading that drives the streams.
    candidate_applications: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship()
    source: Mapped[Source] = relationship()
    grounding: Mapped[list["ProfileGrounding"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="ProfileGrounding.field_name",
    )


class ProfileGrounding(Base):
    """One profile statement's verbatim quote + the asset field it was found in.

    This is the grounding scaffolding made physical: each row proves a generated
    statement is supported by an exact span of the asset's own (already-grounded)
    text.
    """

    __tablename__ = "profile_grounding"
    __table_args__ = (Index("ix_profile_grounding_profile", "profile_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_profile.id", ondelete="CASCADE"), nullable=False
    )
    # The profile statement this grounds, e.g. "problem" or "application[0]".
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    supporting_quote: Mapped[str] = mapped_column(Text, nullable=False)
    # The asset field the quote was located in, e.g. "claims_or_description".
    source_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    profile: Mapped[AssetProfile] = relationship(back_populates="grounding")


class DecisionType(str, enum.Enum):
    """The committee's chosen action for an asset. Humans decide; we record."""

    sprint = "sprint"
    license = "license"
    park = "park"
    hold = "hold"
    reject = "reject"


class OutcomeType(str, enum.Enum):
    """The realised real-world result, recorded later (feeds recalibration)."""

    pending = "pending"
    in_progress = "in_progress"
    spun_out = "spun_out"
    licensed = "licensed"
    parked = "parked"
    abandoned = "abandoned"


class CommitteeDecision(Base):
    """A governance record of the committee's decision on an asset.

    Snapshots the Engine's recommendation at decision time (routing + score) so
    quarterly recalibration can compare the Engine's signal against the human
    decision and the eventual outcome. This is a human input with an actor +
    timestamp, not a factual claim the Engine emits.
    """

    __tablename__ = "committee_decision"
    __table_args__ = (Index("ix_committee_decision_asset", "asset_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, name="decision_type"), nullable=False
    )
    # The Engine's recommendation at the moment of decision (nullable snapshot).
    engine_routing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    engine_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship()


class AssetOutcome(Base):
    """The realised outcome for an asset, recorded when known. Feeds recalibration."""

    __tablename__ = "asset_outcome"
    __table_args__ = (Index("ix_asset_outcome_asset", "asset_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    # Optional link to the decision this outcome followed from.
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("committee_decision.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[OutcomeType] = mapped_column(
        Enum(OutcomeType, name="outcome_type"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship()
    decision: Mapped[CommitteeDecision | None] = relationship()


class AssetScore(Base):
    """The latest persisted ventureability score for an asset (engine output).

    One row per asset (replaced on re-score). Stores the overall value, coverage,
    the corroboration routing, and the per-dimension breakdown so the dashboard
    and clustering can rank on live engine scores without re-running the pipeline.
    A derived signal — explainable, not a human decision.
    """

    __tablename__ = "asset_score"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_asset_score_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    ventureability: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    routing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # [{dimension, value, rationale}] — the explainable breakdown.
    dimensions: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship()


class AssetSynthesis(Base):
    """The decision-oriented reading the committee sees first (L5 output).

    Generated by an LLM AFTER the streams/scoring run, from the engine's OWN
    derived signals (score, routing, evidence) — never from raw invention text.
    It is advisory/analysis (not a grounded factual claim and not a human
    decision): a one-line recommendation, a short market-framed reading, and the
    open questions the first sprint gate must answer. One row per asset, replaced
    on re-run. Absent when no capable LLM produced it (e.g. offline demo).
    """

    __tablename__ = "asset_synthesis"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_asset_synthesis_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    open_questions: Mapped[list] = mapped_column(JSONB, nullable=False)
    # The engine signals the synthesis was derived from, for transparency.
    basis: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    asset: Mapped[Asset] = relationship()


class RecalibrationLog(Base):
    """An audit record of one quarterly recalibration run.

    Recalibration only *proposes* (humans decide whether to retune). Each run
    captures the sample it analysed, the calibration statistics, the proposed
    cutoff, the verdict, and a snapshot of the weights in force — so every
    recommendation is reproducible and auditable.
    """

    __tablename__ = "recalibration_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    good_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bad_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_score_good: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_score_bad: Mapped[float | None] = mapped_column(Float, nullable=True)
    separation: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_cutoff: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    weights_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
