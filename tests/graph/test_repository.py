"""T10: graph persistence — entity resolution + idempotent relationships."""

from __future__ import annotations

from forge.db.models import RelationshipType, Strength
from forge.graph import add_relationship, get_companies, resolve_company


def test_resolve_merges_by_normalised_name(session):
    a, created_a = resolve_company(session, name="Aurora Photonics GmbH")
    b, created_b = resolve_company(session, name="aurora photonics")  # same key
    session.commit()
    assert created_a and not created_b
    assert a.id == b.id
    assert len(get_companies(session)) == 1


def test_resolve_merges_by_registry_id_despite_name_spelling(session):
    a, _ = resolve_company(session, name="Aurora Photonics GmbH", registry_id="PIC-3")
    b, created = resolve_company(session, name="Aurora Optics Ltd", registry_id="PIC-3")
    session.commit()
    assert not created and a.id == b.id  # registry_id is the strong match


def test_resolve_fills_missing_fields_without_overwriting(session):
    a, _ = resolve_company(session, name="Aurora", country="DE")
    resolve_company(session, name="Aurora", country="FR", sector="photonics")
    session.commit()
    assert a.country == "DE"  # not overwritten
    assert a.sector == "photonics"  # filled in


def test_add_relationship_is_idempotent(session):
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    kw = dict(
        type=RelationshipType.collaborative_project,
        source_layer=0,
        topic="PHOTON-EDGE",
        source_ref="cordis:project:101001234",
    )
    _, first = add_relationship(session, company, **kw)
    _, second = add_relationship(session, company, **kw)
    session.commit()
    assert first and not second
    assert len(company.relationships) == 1
    assert company.relationships[0].strength is Strength.medium


def test_distinct_source_projects_are_separate_ties(session):
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    add_relationship(
        session, company, type=RelationshipType.collaborative_project,
        source_layer=0, topic="P1", source_ref="cordis:project:1",
    )
    add_relationship(
        session, company, type=RelationshipType.collaborative_project,
        source_layer=0, topic="P2", source_ref="cordis:project:2",
    )
    session.commit()
    assert len(company.relationships) == 2
