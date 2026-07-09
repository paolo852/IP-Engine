"""Relationship-graph persistence (T10): resolve companies, add relationships.

Writes go through ``resolve_company`` (entity resolution: registry_id first, then
normalised name) so re-ingesting the same firm merges rather than duplicates, and
``add_relationship`` (idempotent on company+type+topic+source) so re-running a
Layer-0 population does not pile up duplicate ties. These flush but do not commit;
the caller owns the transaction boundary.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db.models import Company, Relationship, RelationshipType, Strength
from .entities import normalize_company_name


def _fill_missing(company: Company, **fields) -> None:
    """Enrich a resolved company's empty fields without overwriting known values."""
    for key, value in fields.items():
        if value and not getattr(company, key):
            setattr(company, key, value)


def resolve_company(
    session: Session,
    *,
    name: str,
    registry_id: str | None = None,
    sector: str | None = None,
    size: str | None = None,
    country: str | None = None,
) -> tuple[Company, bool]:
    """Find-or-create a company by entity resolution. Returns (company, created).

    Match order: exact ``registry_id`` (strong), then normalised name. A resolved
    company has its missing attributes filled in from this record.
    """
    if not name or not name.strip():
        raise ValueError("company name is required")
    norm = normalize_company_name(name)

    existing: Company | None = None
    if registry_id:
        existing = session.execute(
            select(Company).where(Company.registry_id == registry_id)
        ).scalars().first()
    if existing is None:
        existing = session.execute(
            select(Company).where(Company.normalized_name == norm)
        ).scalars().first()

    if existing is not None:
        _fill_missing(
            existing, registry_id=registry_id, sector=sector, size=size, country=country
        )
        return existing, False

    company = Company(
        name=name.strip(),
        normalized_name=norm,
        registry_id=registry_id,
        sector=sector,
        size=size,
        country=country,
    )
    session.add(company)
    session.flush()  # assign id for relationships
    return company, True


def _eq_or_null(column, value):
    return column.is_(None) if value is None else column == value


def add_relationship(
    session: Session,
    company: Company,
    *,
    type: RelationshipType,
    source_layer: int,
    university_unit: str | None = None,
    topic: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    strength: Strength = Strength.medium,
    source_ref: str | None = None,
) -> tuple[Relationship, bool]:
    """Add a relationship idempotently. Returns (relationship, created).

    Dedup key: (company, type, topic, source_ref) — the same tie from the same
    source is recorded once, so Layer-0 re-runs converge.
    """
    existing = session.execute(
        select(Relationship).where(
            Relationship.company_id == company.id,
            Relationship.type == type,
            _eq_or_null(Relationship.topic, topic),
            _eq_or_null(Relationship.source_ref, source_ref),
        )
    ).scalars().first()
    if existing is not None:
        return existing, False

    rel = Relationship(
        company=company,
        type=type,
        university_unit=university_unit,
        topic=topic,
        start_date=start_date,
        end_date=end_date,
        strength=strength,
        source_layer=source_layer,
        source_ref=source_ref,
    )
    session.add(rel)
    session.flush()
    return rel, True


def get_companies(session: Session) -> list[Company]:
    """All companies, with their relationships eagerly loaded (contacts excluded)."""
    stmt = (
        select(Company)
        .options(selectinload(Company.relationships))
        .order_by(Company.name)
    )
    return list(session.execute(stmt).scalars())


def find_company(session: Session, company_id: uuid.UUID) -> Company | None:
    stmt = (
        select(Company)
        .where(Company.id == company_id)
        .options(selectinload(Company.relationships))
    )
    return session.execute(stmt).scalar_one_or_none()


def get_relationships_for(session: Session, company_id: uuid.UUID) -> list[Relationship]:
    stmt = (
        select(Relationship)
        .where(Relationship.company_id == company_id)
        .order_by(Relationship.source_layer, Relationship.created_at)
    )
    return list(session.execute(stmt).scalars())
