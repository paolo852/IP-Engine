"""L1 ingestion & connectors.

A connector pulls raw records from one source, normalises them into the L2 asset
schema with provenance, and persists them. The framework guarantees the cross-
cutting rules so individual connectors do not re-implement them:

* fault tolerance — one bad record (or a whole failing source) never blocks the
  rest of a run; failures are isolated and reported (rule 7);
* resumable / incremental — re-running skips records already ingested (rule 7);
* grounding — normalisation must attach provenance for every factual field, and
  persistence (``save_asset``) refuses anything ungrounded (rule 1).
"""

from .base import Connector, IngestReport, RawRecord, RecordError

__all__ = ["Connector", "IngestReport", "RawRecord", "RecordError"]
