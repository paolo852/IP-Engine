"""T12: dual-track company lists — split, graph-prioritised ranking, contact gate."""

from __future__ import annotations

from forge.config import load_governance_config
from forge.db.models import (
    Contact,
    RelationshipType,
    Strength,
    Track,
)
from forge.governance import Principal
from forge.graph import add_relationship, resolve_company
from forge.matching import NeedHypothesisDraft, build_company_lists, save_need_hypotheses
from forge.repository import save_asset

from ..synthetic.assets import synthetic_patent_bundle

GOV = load_governance_config("config/governance.yaml")


def _company(session, name, *, related: bool):
    company, _ = resolve_company(session, name=name, country="DE")
    if related:
        add_relationship(
            session, company, type=RelationshipType.collaborative_project,
            source_layer=0, topic="PHOTON-EDGE", source_ref="cordis:project:1",
        )
    return company


def _draft(company, *, track, strength):
    return NeedHypothesisDraft(
        company_id=company.id, track=track, strength=strength,
        hypothesised_need=f"Hypothesis (unvalidated): {company.name}",
        evidence=[], rationale="",
    )


def _seed(session):
    asset = save_asset(session, synthetic_patent_bundle())
    producer_related = _company(session, "Aurora Photonics GmbH", related=True)
    producer_cold = _company(session, "Zenith Optics Ltd", related=False)
    customer = _company(session, "Global Foundry", related=True)
    session.flush()
    save_need_hypotheses(
        session, asset,
        [
            _draft(producer_cold, track=Track.producer, strength=Strength.strong),
            _draft(producer_related, track=Track.producer, strength=Strength.medium),
            _draft(customer, track=Track.customer, strength=Strength.weak),
        ],
    )
    return asset


def test_lists_split_by_track_and_are_not_merged(session):
    asset = _seed(session)
    lists = build_company_lists(session, asset.id)
    assert {e.name for e in lists.producer} == {"Aurora Photonics GmbH", "Zenith Optics Ltd"}
    assert [e.name for e in lists.customer] == ["Global Foundry"]
    assert lists.total() == 3


def test_related_companies_rank_above_stronger_unrelated_ones(session):
    asset = _seed(session)
    lists = build_company_lists(session, asset.id)
    # Aurora is related (medium); Zenith is unrelated but strong — related wins.
    assert [e.name for e in lists.producer] == ["Aurora Photonics GmbH", "Zenith Optics Ltd"]
    aurora = lists.producer[0]
    assert aurora.related and aurora.relationship_types == ["collaborative_project"]
    assert aurora.source_layers == [0]


def test_contact_flag_hidden_without_view_contacts(session):
    asset = _seed(session)
    # No principal -> hidden; an analyst (no view_contacts) -> still hidden.
    plain = build_company_lists(session, asset.id)
    assert all(e.has_contact is None for e in plain.producer)

    analyst = build_company_lists(
        session, asset.id, principal=Principal("a", "analyst"), governance=GOV
    )
    assert all(e.has_contact is None for e in analyst.producer)


def test_contact_flag_visible_to_view_contacts_role(session):
    asset = _seed(session)
    # An admin holds view_contacts: the existence flag is revealed (still no
    # contact details — just whether one exists).
    lists = build_company_lists(session, asset.id, principal=Principal("root", "admin"), governance=GOV)
    target = next(e for e in lists.producer if e.name == "Aurora Photonics GmbH")
    assert target.has_contact is False  # revealed, and there is no contact yet

    from forge.graph import find_company
    company = find_company(session, target.company_id)
    session.add(Contact(company=company, person="Jane Doe", lawful_basis=True))
    session.commit()

    lists2 = build_company_lists(session, asset.id, principal=Principal("root", "admin"), governance=GOV)
    target2 = next(e for e in lists2.producer if e.name == "Aurora Photonics GmbH")
    assert target2.has_contact is True
