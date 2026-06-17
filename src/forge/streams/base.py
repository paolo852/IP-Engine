"""Common shapes every cross-referencing stream produces.

A stream emits ``SubSignal``s (measured aggregates) each backed by
``EvidenceRecord``s (the normalised, persistable findings). Keeping the shape
common lets later slices compare streams for agreement/conflict without caring
how each one was gathered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..db.models import Licence


@dataclass
class SourceSpec:
    """Where an evidence item came from (becomes a Source row on persist)."""

    source_type: str
    licence: Licence
    locator: str


@dataclass
class EvidenceRecord:
    """One normalised finding — the common cross-stream record (spec L3)."""

    stream: str
    match_strength: float  # retrieval relevance in [0, 1], not a venture score
    snippet: str
    source: SourceSpec
    link: str | None = None
    observed_at: datetime | None = None


@dataclass
class SubSignal:
    """A measured aggregate for one stream dimension, with its evidence."""

    name: str
    value: float
    detail: str
    evidence: list[EvidenceRecord] = field(default_factory=list)


@dataclass
class StreamResult:
    """All sub-signals (and their evidence) a stream produced for one asset."""

    stream: str
    sub_signals: list[SubSignal] = field(default_factory=list)

    def evidence(self) -> list[EvidenceRecord]:
        return [rec for signal in self.sub_signals for rec in signal.evidence]

    def signal(self, name: str) -> SubSignal | None:
        return next((s for s in self.sub_signals if s.name == name), None)
