"""S4 evidence persists into the shared evidence store with public provenance."""

from __future__ import annotations

from forge.config import load_taxonomy_config
from forge.repository import get_evidence, save_asset, save_stream_result
from forge.streams.s4_taxonomy import S4TaxonomyStream

from ..synthetic.assets import synthetic_patent_bundle
from .fakes import profile


def test_s4_evidence_round_trips(session):
    asset = save_asset(session, synthetic_patent_bundle())
    result = S4TaxonomyStream(load_taxonomy_config("config/taxonomy.yaml")).run(
        profile([], solution="a photonic optical edge computing interconnect")
    )

    save_stream_result(session, asset, result)
    session.expunge_all()

    rows = get_evidence(session, asset.id, stream="S4_taxonomy")
    assert rows, "expected at least one taxonomy evidence row"
    assert all(r.source.source_type == "eu_taxonomy" for r in rows)
    assert all(r.source.licence.value == "public" for r in rows)
    assert any("Aligns with" in r.snippet for r in rows)
