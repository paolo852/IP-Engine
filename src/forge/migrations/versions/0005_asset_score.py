"""asset score

Revision ID: 0005_asset_score
Revises: 0004_recalibration_log
Create Date: 2026-06-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_asset_score"
down_revision: Union[str, None] = "0004_recalibration_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'asset_score',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('ventureability', sa.Float(), nullable=True),
        sa.Column('coverage', sa.Float(), nullable=False),
        sa.Column('routing', sa.String(length=32), nullable=True),
        sa.Column('dimensions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['asset.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_id', name='uq_asset_score_asset'),
    )


def downgrade() -> None:
    op.drop_table('asset_score')
