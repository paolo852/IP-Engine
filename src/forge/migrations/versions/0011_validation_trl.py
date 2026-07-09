"""need validation + inventor TRL check

Revision ID: 0011_validation_trl
Revises: 0010_need_hypothesis
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_validation_trl"
down_revision: Union[str, None] = "0010_need_hypothesis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

need_outcome_enum = sa.Enum(
    "need_confirmed", "need_denied", "no_response", name="need_outcome"
)
# 'track' enum already exists (0010); reference without re-creating.
track_enum = postgresql.ENUM("customer", "producer", name="track", create_type=False)


def upgrade() -> None:
    op.create_table(
        "need_validation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("track", track_enum, nullable=False),
        sa.Column("outcome", need_outcome_enum, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("validated_by", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_need_validation_asset", "need_validation", ["asset_id"])

    op.create_table(
        "inventor_trl_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("trl_band", sa.String(length=16), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventor_trl_check_asset", "inventor_trl_check", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_inventor_trl_check_asset", table_name="inventor_trl_check")
    op.drop_table("inventor_trl_check")
    op.drop_index("ix_need_validation_asset", table_name="need_validation")
    op.drop_table("need_validation")
    need_outcome_enum.drop(op.get_bind(), checkfirst=False)
