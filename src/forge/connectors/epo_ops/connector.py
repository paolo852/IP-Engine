"""EpoOpsConnector: OPS biblio -> grounded L2 asset bundles."""

from __future__ import annotations

from datetime import datetime

from ...db.models import Asset, AssetType, Licence, Source
from ...repository import AssetBundle, ProvenanceEntry
from ..base import Connector, RawRecord
from .client import OpsClient
from .parser import ParsedPatent, parse_biblio


class EpoOpsConnector(Connector):
    name = "epo_ops"
    source_type = "epo_ops"
    licence = Licence.free  # OPS is free/public — never licensed raw (rule 5)

    def __init__(self, client: OpsClient) -> None:
        self.client = client
        self.source_layer = client.settings.source_layer

    def fetch_one(self, ref: str) -> RawRecord:
        return self.client.fetch_biblio(ref)

    def normalise(self, raw: RawRecord) -> list[AssetBundle]:
        patents = parse_biblio(raw.payload)
        return [
            self._to_bundle(p, raw.retrieved_at)
            for p in patents
            if p.publication_id  # skip fragments we cannot key/dedup
        ]

    def _to_bundle(self, p: ParsedPatent, retrieved_at: datetime) -> AssetBundle:
        # One Source per document. locator is the canonical publication id so
        # re-runs dedup per document; raw_ref is a POINTER, never the payload
        # (licence separation, rule 5).
        source = Source(
            source_type=self.source_type,
            licence=self.licence,
            locator=p.publication_id,
            raw_ref=f"epodoc:{p.publication_id}",
            retrieved_at=retrieved_at,
        )

        key_dates = {
            k: v
            for k, v in (
                ("publication_date", p.publication_date),
                ("application_date", p.application_date),
                ("priority_date", p.priority_date),
            )
            if v
        }

        asset = Asset(
            asset_type=AssetType.patent,
            source_layer=self.source_layer,
            title=p.title,
            abstract=p.abstract,
            # Biblio carries no claims/description; left for a later enrichment slice.
            claims_or_description=None,
            inventors=p.inventors or None,
            owners=p.applicants or None,
            co_owners=None,
            legal_status=None,  # OPS legal status is a separate endpoint (stub).
            key_dates=key_dates or None,
            fee_status=None,
            encumbrances=None,
            linked_publications=None,
        )

        # Ground every factual field that actually got a value, all from this
        # one source. save_asset will reject the bundle if any populated factual
        # field is left ungrounded (rule 1).
        provenance = [
            ProvenanceEntry(field_name=name, source=source, note="EPO OPS biblio")
            for name in asset.populated_groundable_fields()
        ]
        return AssetBundle(asset=asset, provenance=provenance)
