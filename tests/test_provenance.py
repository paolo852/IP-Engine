"""Grounding rule (non-negotiable rule 1): no source -> no claim, enforced at save."""

from __future__ import annotations

import pytest

from forge.db.models import Asset, AssetType, Licence, Source
from forge.repository import (
    AssetBundle,
    GroundingError,
    ProvenanceEntry,
    get_asset,
    provenance_map,
    save_asset,
    ungrounded_fields,
)

from .synthetic.assets import synthetic_patent_bundle, synthetic_source


def test_ungrounded_field_is_rejected(session):
    # An asset with a factual field (abstract) but no provenance for it.
    src = synthetic_source()
    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="grounded title",
        abstract="ungrounded abstract — has no source",
    )
    bundle = AssetBundle(
        asset=asset,
        provenance=[ProvenanceEntry(field_name="title", source=src)],
    )

    with pytest.raises(GroundingError, match="abstract"):
        save_asset(session, bundle)

    # Nothing was committed: the asset must not exist.
    session.rollback()
    assert get_asset(session, asset.id) is None


def test_ungrounded_fields_helper_pinpoints_gaps():
    bundle = synthetic_patent_bundle()
    # Pretend we only grounded the title.
    missing = ungrounded_fields(bundle.asset, {"title"})
    assert "abstract" in missing and "title" not in missing


def test_multiple_sources_can_corroborate_one_field(session):
    # The model allows several provenance rows per field (corroboration).
    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="corroborated title",
    )
    src_a = Source(source_type="synthetic", licence=Licence.synthetic, locator="syn://a")
    src_b = Source(source_type="synthetic", licence=Licence.synthetic, locator="syn://b")
    bundle = AssetBundle(
        asset=asset,
        provenance=[
            ProvenanceEntry(field_name="title", source=src_a),
            ProvenanceEntry(field_name="title", source=src_b),
        ],
    )

    save_asset(session, bundle)
    session.expunge_all()

    loaded = get_asset(session, asset.id)
    pmap = provenance_map(loaded)
    assert len(pmap["title"]) == 2
    assert {s.locator for s in pmap["title"]} == {"syn://a", "syn://b"}
