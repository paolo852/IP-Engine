"""Build-order slice 1 acceptance: round-trip a synthetic asset through Postgres."""

from __future__ import annotations

from forge.repository import get_asset, provenance_map, save_asset

from .synthetic.assets import minimal_grounded_bundle, synthetic_patent_bundle


def test_round_trip_preserves_every_field(session):
    bundle = synthetic_patent_bundle()
    original = bundle.asset
    snapshot = {
        "asset_type": original.asset_type,
        "source_layer": original.source_layer,
        "title": original.title,
        "abstract": original.abstract,
        "claims_or_description": original.claims_or_description,
        "inventors": list(original.inventors),
        "owners": list(original.owners),
        "co_owners": list(original.co_owners),
        "legal_status": original.legal_status,
        "key_dates": dict(original.key_dates),
        "fee_status": original.fee_status,
        "encumbrances": original.encumbrances,
        "linked_publications": list(original.linked_publications),
    }

    saved = save_asset(session, bundle)
    asset_id = saved.id

    # New session-less identity: expunge so we read back from the DB, not memory.
    session.expunge_all()
    loaded = get_asset(session, asset_id)

    assert loaded is not None
    for field, expected in snapshot.items():
        assert getattr(loaded, field) == expected, field
    assert loaded.created_at is not None and loaded.updated_at is not None


def test_round_trip_preserves_provenance_for_every_field(session):
    bundle = synthetic_patent_bundle()
    saved = save_asset(session, bundle)
    session.expunge_all()

    loaded = get_asset(session, saved.id)
    pmap = provenance_map(loaded)

    # Every populated factual field came back with at least one source.
    for field in loaded.populated_groundable_fields():
        assert field in pmap and len(pmap[field]) >= 1, field
    # And the source round-trips its licence (synthetic, never licensed raw).
    any_source = next(iter(pmap.values()))[0]
    assert any_source.licence.value == "synthetic"


def test_minimal_asset_round_trips(session):
    saved = save_asset(session, minimal_grounded_bundle())
    session.expunge_all()
    loaded = get_asset(session, saved.id)
    assert loaded.title == "Synthetic soil-moisture dataset (invented)"
    assert loaded.populated_groundable_fields() == ["title"]


def test_get_unknown_asset_returns_none(session):
    import uuid

    assert get_asset(session, uuid.uuid4()) is None
