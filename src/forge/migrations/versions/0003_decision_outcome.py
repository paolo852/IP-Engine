"""committee decision + outcome

Adds the L5 governance store: the committee's decision per asset (with the
Engine's recommendation snapshot) and the realised outcome that feeds
quarterly recalibration.

Revision ID: 0003_decision_outcome
Revises: 0002_asset_profile
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_decision_outcome"
down_revision: Union[str, None] = "0002_asset_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

decision_type = sa.Enum(
    "sprint", "license", "park", "hold", "reject", name="decision_type"
)
outcome_type = sa.Enum(
    "pending", "in_progress", "spun_out", "licensed", "parked", "abandoned",
    name="outcome_type",
)


def upgrade() -> None:
    op.create_table(
        "committee_decision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("decision", decision_type, nullable=False),
        sa.Column("engine_routing", sa.String(length=32), nullable=True),
        sa.Column("engine_score", sa.Float(), nullable=True),
        sa.Column("engine_coverage", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_committee_decision_asset", "committee_decision", ["asset_id"], unique=False
    )
    op.create_table(
        "asset_outcome",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", outcome_type, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["committee_decision.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_outcome_asset", "asset_outcome", ["asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_outcome_asset", table_name="asset_outcome")
    op.drop_table("asset_outcome")
    op.drop_index("ix_committee_decision_asset", table_name="committee_decision")
    op.drop_table("committee_decision")
    outcome_type.drop(op.get_bind(), checkfirst=False)
    decision_type.drop(op.get_bind(), checkfirst=False)
