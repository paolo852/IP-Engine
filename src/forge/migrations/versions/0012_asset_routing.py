"""two-axis routing

Revision ID: 0012_asset_routing
Revises: 0011_validation_trl
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_asset_routing"
down_revision: Union[str, None] = "0011_validation_trl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

routing_status_enum = sa.Enum("pending", "ready", name="routing_status")
need_axis_enum = sa.Enum("customer", "producer", "none", name="need_axis")
trl_axis_enum = sa.Enum("high", "low", name="trl_axis")
route_type_enum = sa.Enum(
    "venture", "licensing", "maturation", "option", "park", name="route_type"
)


def upgrade() -> None:
    op.create_table(
        "asset_routing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("status", routing_status_enum, nullable=False),
        sa.Column("need_axis", need_axis_enum, nullable=True),
        sa.Column("trl_axis", trl_axis_enum, nullable=True),
        sa.Column("suggested_route", route_type_enum, nullable=True),
        sa.Column("committee_decision", sa.String(length=32), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_asset_routing_asset"),
    )


def downgrade() -> None:
    op.drop_table("asset_routing")
    route_type_enum.drop(op.get_bind(), checkfirst=False)
    trl_axis_enum.drop(op.get_bind(), checkfirst=False)
    need_axis_enum.drop(op.get_bind(), checkfirst=False)
    routing_status_enum.drop(op.get_bind(), checkfirst=False)
