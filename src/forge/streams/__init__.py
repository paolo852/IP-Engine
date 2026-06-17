"""L3 cross-referencing streams.

Each stream turns an asset's profile into typed query objects (derived from the
problem space, not the patent's own wording), fans out to a source, and
normalises every finding into common ``EvidenceRecord``s (source, date,
match-strength, snippet, link). Cross-referencing across streams is corroboration
analysis — agreement vs conflict — NOT averaging four numbers; that lands when
more than one stream exists. S2 (patents/citations) is built first (free).
"""

from .base import EvidenceRecord, SourceSpec, StreamResult, SubSignal

__all__ = ["EvidenceRecord", "SourceSpec", "StreamResult", "SubSignal"]
