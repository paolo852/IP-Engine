"""asset profile market decomposition

Revision ID: 0007_profile_applications
Revises: 0006_asset_synthesis
Create Date: 2026-06-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_profile_applications"
down_revision: Union[str, None] = "0006_asset_synthesis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_profile", sa.Column("technology_summary", sa.Text(), nullable=True)
    )
    op.add_column(
        "asset_profile",
        sa.Column(
            "candidate_applications",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("asset_profile", "candidate_applications")
    op.drop_column("asset_profile", "technology_summary")
