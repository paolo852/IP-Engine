"""Synthetic asset fixtures — SYNTHETIC DATA ONLY (non-negotiable rule 4).

No real or confidential portfolios. Every value here is invented; sources are
marked Licence.synthetic so nothing can be mistaken for licensed raw data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from forge.db.models import Asset, AssetType, Licence, Source
from forge.repository import AssetBundle, ProvenanceEntry


def synthetic_source(locator: str = "synthetic://demo/patent/EP-FAKE-0001") -> Source:
    return Source(
        source_type="synthetic",
        licence=Licence.synthetic,
        locator=locator,
        retrieved_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )


def synthetic_patent_bundle() -> AssetBundle:
    """A fully-populated, fully-grounded synthetic patent asset.

    Every populated factual field is backed by a ProvenanceEntry, so this bundle
    satisfies the grounding rule and can be persisted by ``save_asset``.
    """
    src = synthetic_source()
    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="Low-power photonic interconnect for edge AI accelerators",
        abstract=(
            "A photonic interconnect architecture reducing inter-chip energy per "
            "bit for edge inference workloads (invented; not a real patent)."
        ),
        claims_or_description=(
            "1. An interconnect comprising a micro-ring modulator array coupled to "
            "a silicon waveguide... (synthetic claim text)."
        ),
        inventors=["A. Rossi", "B. Bianchi"],
        owners=["Synthetic Research Org"],
        co_owners=["Synthetic University"],
        legal_status="granted",
        key_dates={
            "priority_date": "2018-03-04",
            "filing_date": "2019-03-01",
            "grant_date": "2022-06-21",
        },
        fee_status="lapsing",
        encumbrances="none recorded",
        linked_publications=["doi:10.0000/synthetic.2020.0001"],
        classification_codes=["G02B 6/12", "H04B 10/00"],
    )

    # One provenance entry per populated factual field — all from the same
    # synthetic source here, but the model supports several sources per field.
    fields = [
        "title",
        "abstract",
        "claims_or_description",
        "inventors",
        "owners",
        "co_owners",
        "legal_status",
        "key_dates",
        "fee_status",
        "encumbrances",
        "linked_publications",
        "classification_codes",
    ]
    provenance = [
        ProvenanceEntry(field_name=f, source=src, note="synthetic fixture")
        for f in fields
    ]
    return AssetBundle(asset=asset, provenance=provenance)


def minimal_grounded_bundle() -> AssetBundle:
    """Smallest valid asset: a single grounded factual field (title)."""
    src = synthetic_source("synthetic://demo/minimal")
    asset = Asset(
        asset_type=AssetType.dataset,
        source_layer="L1.synthetic",
        title="Synthetic soil-moisture dataset (invented)",
    )
    return AssetBundle(
        asset=asset,
        provenance=[ProvenanceEntry(field_name="title", source=src)],
    )
