"""Dual-track company lists (T12) — customer vs producer, graph-prioritised.

Per asset the engine presents TWO named lists (never merged, brief §L3.4):
a **customer** list (firms that have the problem) and a **producer/licensee** list
(firms that would make or sell it). They are built from the need hypotheses (T11),
which are already tracked customer/producer. Companies related through the
Relationship Graph rank to the top, tagged with their relationship type(s) and
source layer(s), and — only behind the stricter ``view_contacts`` RBAC gate —
whether a contact exists. Company-level matching works with contacts hidden.

These are still HYPOTHESES (rule 4): the list is a ranked set of firms to test,
not confirmed customers or licensees.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db.models import Company, NeedHypothesis, Strength, Track
from ..governance import GovernanceConfig, Principal, permissions_for

_STRENGTH_RANK = {Strength.weak: 0, Strength.medium: 1, Strength.strong: 2}


@dataclass
class CompanyListing:
    company_id: uuid.UUID
    name: str
    country: str | None
    related: bool
    relationship_types: list[str]
    source_layers: list[int]
    strength: str
    hypothesis: str
    has_contact: bool | None  # None = hidden behind RBAC (view_contacts)


@dataclass
class DualTrackLists:
    asset_id: uuid.UUID
    customer: list[CompanyListing] = field(default_factory=list)
    producer: list[CompanyListing] = field(default_factory=list)

    def total(self) -> int:
        return len(self.customer) + len(self.producer)


def _may_reveal_contacts(principal: Principal | None, gov: GovernanceConfig | None) -> bool:
    if principal is None or gov is None:
        return False
    try:
        return "view_contacts" in permissions_for(principal.role, gov)
    except Exception:  # noqa: BLE001 - unknown role -> reveal nothing
        return False


def _listing(h: NeedHypothesis, *, reveal_contacts: bool) -> CompanyListing:
    company = h.company
    rels = list(company.relationships)
    return CompanyListing(
        company_id=company.id,
        name=company.name,
        country=company.country,
        related=bool(rels),
        relationship_types=sorted({r.type.value for r in rels}),
        source_layers=sorted({r.source_layer for r in rels}),
        strength=h.strength.value,
        hypothesis=h.hypothesised_need,
        has_contact=(len(company.contacts) > 0) if reveal_contacts else None,
    )


def _rank_key(listing: CompanyListing):
    # Related firms first, then stronger hypotheses, then name (stable, readable).
    return (
        0 if listing.related else 1,
        -_STRENGTH_RANK.get(Strength(listing.strength), 0),
        listing.name.lower(),
    )


def build_company_lists(
    session: Session,
    asset_id: uuid.UUID,
    *,
    principal: Principal | None = None,
    governance: GovernanceConfig | None = None,
) -> DualTrackLists:
    """Build the two graph-prioritised company lists for an asset from its
    need hypotheses. ``principal``/``governance`` gate the contact-exists flag."""
    reveal = _may_reveal_contacts(principal, governance)
    stmt = (
        select(NeedHypothesis)
        .where(NeedHypothesis.asset_id == asset_id)
        .options(
            selectinload(NeedHypothesis.company).selectinload(Company.relationships),
            selectinload(NeedHypothesis.company).selectinload(Company.contacts),
        )
    )
    lists = DualTrackLists(asset_id=asset_id)
    for h in session.execute(stmt).scalars():
        listing = _listing(h, reveal_contacts=reveal)
        (lists.customer if h.track is Track.customer else lists.producer).append(listing)

    lists.customer.sort(key=_rank_key)
    lists.producer.sort(key=_rank_key)
    return lists
