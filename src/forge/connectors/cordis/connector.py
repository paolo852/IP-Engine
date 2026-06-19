"""CordisConnector: CORDIS result JSON -> grounded L2 project-result bundles."""

from __future__ import annotations

from datetime import datetime

from ...db.models import Asset, AssetType, Licence, Source
from ...repository import AssetBundle, ProvenanceEntry
from ..base import Connector, RawRecord
from .client import CordisClient
from .parser import ParsedResult, parse_results


class CordisConnector(Connector):
    name = "cordis"
    source_type = "cordis"
    licence = Licence.public  # CORDIS is EU public open data (CC BY) — never licensed raw

    def __init__(self, client: CordisClient) -> None:
        self.client = client
        self.source_layer = client.settings.source_layer

    def fetch_one(self, ref: str) -> RawRecord:
        return self.client.fetch_result(ref)

    def normalise(self, raw: RawRecord) -> list[AssetBundle]:
        bundles: list[AssetBundle] = []
        for r in parse_results(raw.payload):
            # Need at least one groundable fact (so provenance exists) and a stable
            # locator to dedup on — otherwise skip the fragment (rule 7).
            if not (r.title or r.abstract or r.description or r.owners):
                continue
            if not (r.url or r.result_id):
                continue
            bundles.append(self._to_bundle(r, raw.retrieved_at, raw.locator))
        return bundles

    def _to_bundle(
        self, r: ParsedResult, retrieved_at: datetime, fallback_locator: str
    ) -> AssetBundle:
        locator = r.url or (f"cordis:result:{r.result_id}" if r.result_id else fallback_locator)
        source = Source(
            source_type=self.source_type,
            licence=self.licence,
            locator=locator,  # canonical per-result id -> idempotent re-runs
            raw_ref=f"cordis:result:{r.result_id}" if r.result_id else None,
            retrieved_at=retrieved_at,
        )

        # The project end date is what the project_result dormancy ruleset reads
        # (ended_in_window); store it under the key the ruleset looks for.
        key_dates = {"end_date": r.end_date} if r.end_date else None
        linked = [f"cordis:project:{r.project_id}"] if r.project_id else None

        asset = Asset(
            asset_type=AssetType.project_result,
            source_layer=self.source_layer,
            title=r.title,
            abstract=r.abstract,
            # The full exploitable-result text is the closest analogue to a patent's
            # description; profiling/streams read it like any other body text.
            claims_or_description=r.description,
            owners=r.owners or None,
            key_dates=key_dates,
            linked_publications=linked,
        )

        provenance = [
            ProvenanceEntry(field_name=name, source=source, note="CORDIS result")
            for name in asset.populated_groundable_fields()
        ]
        return AssetBundle(asset=asset, provenance=provenance)
