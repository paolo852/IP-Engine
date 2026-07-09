"""relationship graph: company, relationship, contact

Revision ID: 0009_relationship_graph
Revises: 0008_asset_classification
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_relationship_graph"
down_revision: Union[str, None] = "0008_asset_classification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

relationship_type_enum = sa.Enum(
    "research_contract",
    "collaborative_project",
    "spin_off",
    "industrial_phd",
    "lab_sponsor",
    "alumni_employer",
    "committee_member",
    "other",
    name="relationship_type",
)
strength_enum = sa.Enum("weak", "medium", "strong", name="strength")


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=256), nullable=False),
        sa.Column("registry_id", sa.String(length=64), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("size", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_company_normalized_name"),
    )
    op.create_index("ix_company_registry", "company", ["registry_id"])

    op.create_table(
        "relationship",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("university_unit", sa.String(length=256), nullable=True),
        sa.Column("type", relationship_type_enum, nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("start_date", sa.String(length=32), nullable=True),
        sa.Column("end_date", sa.String(length=32), nullable=True),
        sa.Column("strength", strength_enum, nullable=False),
        sa.Column("source_layer", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "type", "topic", "source_ref", name="uq_relationship_dedup"
        ),
    )
    op.create_index("ix_relationship_company", "relationship", ["company_id"])

    op.create_table(
        "contact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("person", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("lawful_basis", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_company", "contact", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_contact_company", table_name="contact")
    op.drop_table("contact")
    op.drop_index("ix_relationship_company", table_name="relationship")
    op.drop_table("relationship")
    op.drop_index("ix_company_registry", table_name="company")
    op.drop_table("company")
    strength_enum.drop(op.get_bind(), checkfirst=False)
    relationship_type_enum.drop(op.get_bind(), checkfirst=False)
