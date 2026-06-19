"""asset classification codes

Revision ID: 0008_asset_classification
Revises: 0007_profile_applications
Create Date: 2026-06-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_asset_classification"
down_revision: Union[str, None] = "0007_profile_applications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset",
        sa.Column(
            "classification_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("asset", "classification_codes")
