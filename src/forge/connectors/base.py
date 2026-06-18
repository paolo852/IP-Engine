"""Connector framework: the contract + a fault-tolerant, resumable run loop."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Licence, Source
from ..repository import AssetBundle, save_asset


@dataclass
class RawRecord:
    """An unmodified payload fetched from a source, plus where it came from."""

    ref: str  # the input reference requested (e.g. "EP9999999")
    locator: str  # canonical source locator for the fetch (URL / accession)
    payload: bytes
    content_type: str
    retrieved_at: datetime


@dataclass
class RecordError:
    """A single failure during a run — captured, never fatal to the whole run."""

    ref: str
    stage: str  # "fetch" | "normalise" | "save"
    error: str


@dataclass
class IngestReport:
    """Outcome of a run. ``failed`` being non-empty does not abort the others."""

    saved: list[uuid.UUID] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # locators already present
    failed: list[RecordError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (
            f"{len(self.saved)} saved, {len(self.skipped)} skipped, "
            f"{len(self.failed)} failed"
        )


class Connector(ABC):
    """Base class for all L1 connectors.

    Subclasses implement ``fetch_one`` and ``normalise``; the framework owns the
    run loop, failure isolation, and incremental skip-by-locator.
    """

    #: Stable connector name, e.g. "epo_ops".
    name: str
    #: Value written to ``Source.source_type`` for provenance/dedup.
    source_type: str
    #: Licence class of this source (drives licence separation, rule 5).
    licence: Licence

    @abstractmethod
    def fetch_one(self, ref: str) -> RawRecord:
        """Fetch the raw payload for one reference. May raise on failure."""

    @abstractmethod
    def normalise(self, raw: RawRecord) -> list[AssetBundle]:
        """Turn a raw record into zero or more grounded asset bundles.

        Every returned bundle MUST carry provenance for each populated factual
        field; ``save_asset`` enforces this at persistence time.
        """

    def bundle_locator(self, bundle: AssetBundle) -> str:
        """Per-document locator used for incremental dedup.

        Defaults to the first provenance source's locator, which connectors set
        to a canonical per-document id so re-runs skip exactly what is present.
        """
        if not bundle.provenance:
            raise ValueError("bundle has no provenance to derive a locator from")
        return bundle.provenance[0].source.locator

    def existing_locators(self, session: Session) -> set[str]:
        """Locators already ingested for this connector (resumability, rule 7)."""
        rows = session.execute(
            select(Source.locator).where(Source.source_type == self.source_type)
        ).scalars()
        return set(rows)

    def run(
        self,
        refs: Iterable[str],
        session: Session,
        *,
        skip_existing: bool = True,
        policy=None,
    ) -> IngestReport:
        """Ingest each ref, isolating failures and skipping what already exists.

        A failure in one stage of one ref is recorded and the run continues — a
        failing source must not block the others (rule 7). A governance ``policy``
        is enforced at the store seam (a blocked asset is recorded as a failure,
        not raised).
        """
        report = IngestReport()
        seen = self.existing_locators(session) if skip_existing else set()

        for ref in refs:
            try:
                raw = self.fetch_one(ref)
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                report.failed.append(RecordError(ref, "fetch", str(exc)))
                continue

            try:
                bundles = self.normalise(raw)
            except Exception as exc:  # noqa: BLE001
                report.failed.append(RecordError(ref, "normalise", str(exc)))
                continue

            for bundle in bundles:
                locator = self.bundle_locator(bundle)
                if locator in seen:
                    report.skipped.append(locator)
                    continue
                try:
                    saved = save_asset(session, bundle, policy=policy)
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    report.failed.append(RecordError(ref, "save", str(exc)))
                    continue
                report.saved.append(saved.id)
                seen.add(locator)

        return report
