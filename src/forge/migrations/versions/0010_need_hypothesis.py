"""need hypothesis

Revision ID: 0010_need_hypothesis
Revises: 0009_relationship_graph
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_need_hypothesis"
down_revision: Union[str, None] = "0009_relationship_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

track_enum = sa.Enum("customer", "producer", name="track")
# 'strength' enum already exists (created in 0009); reference it without re-creating.
strength_enum = postgresql.ENUM(
    "weak", "medium", "strong", name="strength", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "need_hypothesis",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesised_need", sa.Text(), nullable=False),
        sa.Column("track", track_enum, nullable=False),
        sa.Column("strength", strength_enum, nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "company_id", "track", name="uq_need_hypothesis"),
    )
    op.create_index("ix_need_hypothesis_asset", "need_hypothesis", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_need_hypothesis_asset", table_name="need_hypothesis")
    op.drop_table("need_hypothesis")
    track_enum.drop(op.get_bind(), checkfirst=False)
