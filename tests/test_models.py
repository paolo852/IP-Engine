"""Model-level behaviour: groundable-field detection, licence helper, constraints."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from forge.db.models import (
    GROUNDABLE_FIELDS,
    Asset,
    AssetType,
    Evidence,
    Licence,
    Source,
)

from .synthetic.assets import synthetic_patent_bundle, synthetic_source


def test_populated_groundable_fields_lists_only_nonempty():
    asset = Asset(asset_type=AssetType.patent, source_layer="L1.synthetic", title="x")
    assert asset.populated_groundable_fields() == ["title"]


def test_empty_collections_are_not_counted_as_populated():
    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="",          # empty string -> not populated
        inventors=[],      # empty list -> not populated
        key_dates={},      # empty dict -> not populated
    )
    assert asset.populated_groundable_fields() == []


def test_fully_populated_synthetic_patent_covers_all_groundable_fields():
    bundle = synthetic_patent_bundle()
    assert set(bundle.asset.populated_groundable_fields()) == set(GROUNDABLE_FIELDS)


def test_source_is_licensed_helper():
    assert synthetic_source().is_licensed() is False
    licensed = Source(source_type="dealroom", licence=Licence.licensed_dealroom, locator="x")
    assert licensed.is_licensed() is True


def test_evidence_match_strength_check_constraint(session):
    # Persist an asset + source to satisfy the FKs, then violate the unit-range check.
    bundle = synthetic_patent_bundle()
    session.add(bundle.asset)
    src = bundle.provenance[0].source
    session.add(src)
    session.flush()

    session.add(
        Evidence(asset_id=bundle.asset.id, source_id=src.id, match_strength=1.5)
    )
    with pytest.raises(IntegrityError):
        session.flush()
