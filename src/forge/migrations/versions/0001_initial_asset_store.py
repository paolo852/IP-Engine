"""initial L2 asset store schema

Creates the unified asset store: assets, their provenance-bearing sources,
per-field provenance (grounding rule), and the derived-signal evidence table.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

asset_type_enum = sa.Enum(
    "patent",
    "disclosure",
    "software",
    "dataset",
    "thesis",
    "project_result",
    name="asset_type",
)
licence_enum = sa.Enum(
    "free",
    "public",
    "internal",
    "synthetic",
    "licensed_dealroom",
    "licensed_patstat",
    name="licence",
)


def upgrade() -> None:
    op.create_table(
        "asset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", asset_type_enum, nullable=False),
        sa.Column("source_layer", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("claims_or_description", sa.Text(), nullable=True),
        sa.Column("inventors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("owners", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("co_owners", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("legal_status", sa.String(length=128), nullable=True),
        sa.Column("key_dates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fee_status", sa.String(length=64), nullable=True),
        sa.Column("encumbrances", sa.Text(), nullable=True),
        sa.Column(
            "linked_publications",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("licence", licence_enum, nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("raw_ref", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_strength", sa.Float(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "match_strength >= 0.0 AND match_strength <= 1.0",
            name="ck_evidence_match_strength_unit",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_asset", "evidence", ["asset_id"], unique=False)
    op.create_table(
        "field_provenance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "field_name", "source_id", name="uq_field_provenance"
        ),
    )
    op.create_index(
        "ix_field_provenance_asset", "field_provenance", ["asset_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_field_provenance_asset", table_name="field_provenance")
    op.drop_table("field_provenance")
    op.drop_index("ix_evidence_asset", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("source")
    op.drop_table("asset")
    # Drop the Postgres ENUM types created implicitly above, so a re-upgrade does
    # not collide with leftover types.
    licence_enum.drop(op.get_bind(), checkfirst=False)
    asset_type_enum.drop(op.get_bind(), checkfirst=False)
