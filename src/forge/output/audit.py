"""Automated grounding audit (E11): a single generate→source trace + check.

The grounding rule (rule 1: no source → no claim) is enforced defensively at the
write seams (``save_asset``, ``save_profile``, ``build_brief``). This module is the
*independent* read-side counterpart: it walks everything the engine has already
stored — asset facts, profile statements, cross-stream evidence — and re-derives,
for every stored claim, the source pointer it traces to. Any claim that does not
trace to a source is a violation.

It is read-only and deterministic: the same audit a compliance reviewer would run
by hand, as one function. ``forge audit`` exits non-zero on any violation, so it
doubles as a CI gate over a live store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Asset
from .. import repository as repo


@dataclass
class ClaimTrace:
    """One stored claim and the source pointer(s) it traces back to."""

    layer: str  # "asset" | "profile" | "evidence"
    claim: str  # the field name / statement / signal being grounded
    sources: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.sources)


@dataclass
class AssetAudit:
    asset_id: uuid.UUID
    title: str | None
    traces: list[ClaimTrace] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def claim_count(self) -> int:
        return len(self.traces)

    @property
    def grounded_count(self) -> int:
        return sum(1 for t in self.traces if t.grounded)

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass
class StoreAudit:
    audits: list[AssetAudit] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.audits)

    @property
    def claim_count(self) -> int:
        return sum(a.claim_count for a in self.audits)

    def violations(self) -> list[str]:
        return [f"{a.title or a.asset_id}: {v}" for a in self.audits for v in a.violations]

    def summary(self) -> str:
        grounded = sum(a.grounded_count for a in self.audits)
        viol = sum(len(a.violations) for a in self.audits)
        verdict = "PASS" if self.ok else "FAIL"
        return (
            f"grounding audit {verdict}: {len(self.audits)} assets, "
            f"{grounded}/{self.claim_count} claims traced to a source, {viol} violation(s)"
        )

    def render(self) -> str:
        lines = [self.summary(), ""]
        for a in self.audits:
            head = "ok " if a.ok else "!! "
            lines.append(f"{head}{a.title or '(untitled)'}  [{a.asset_id}]")
            for t in a.traces:
                mark = "·" if t.grounded else "✗"
                src = ", ".join(t.sources) if t.sources else "NO SOURCE"
                lines.append(f"    {mark} [{t.layer}] {t.claim}  ←  {src}")
            for v in a.violations:
                lines.append(f"    ✗ VIOLATION: {v}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _src_label(source) -> str:
    return f"{source.source_type}:{source.locator}"


def audit_asset(session: Session, asset_id: uuid.UUID) -> AssetAudit | None:
    """Trace every stored claim for one asset back to its source(s).

    Returns None if the asset does not exist. Re-checks the grounding rule across
    three layers independently of the write-time gates, so a row that slipped
    through (or was written by a different path) is still caught.
    """
    asset = repo.get_asset(session, asset_id)
    if asset is None:
        return None

    audit = AssetAudit(asset_id=asset.id, title=asset.title)

    # 1. Asset factual fields — each populated groundable field needs provenance.
    pmap = repo.provenance_map(asset)
    for field_name in asset.populated_groundable_fields():
        sources = pmap.get(field_name, [])
        audit.traces.append(
            ClaimTrace("asset", f"asset.{field_name}", [_src_label(s) for s in sources])
        )
        if not sources:
            audit.violations.append(f"asset field '{field_name}' has no source (rule 1)")

    # 2. Profile statements — each grounded statement records the asset field its
    #    verbatim quote came from; the enrichment act itself is a Source too.
    profile = repo.get_profile(session, asset.id)
    if profile is not None:
        prof_src = _src_label(profile.source) if profile.source else None
        if prof_src is None:
            audit.violations.append("profile has no enrichment source (rule 1)")
        grounded_names = set()
        for g in profile.grounding:
            grounded_names.add(g.field_name)
            pointers = []
            if g.source_field:
                pointers.append(f"asset.{g.source_field}")
            if prof_src:
                pointers.append(prof_src)
            audit.traces.append(ClaimTrace("profile", g.field_name, pointers))
            if not g.source_field:
                audit.violations.append(
                    f"profile statement '{g.field_name}' has no located quote (rule 1)"
                )
        # Every emitted statement must carry a grounding row, not just have one stored.
        expected = {"problem", "solution"} | {
            f"application[{i}]" for i in range(len(profile.applications or []))
        }
        for missing in sorted(expected - grounded_names):
            audit.violations.append(f"profile statement '{missing}' is ungrounded (rule 1)")

    # 3. Cross-stream evidence — each derived signal carries its own source.
    for ev in repo.get_evidence(session, asset.id):
        claim = f"{ev.stream}: {(ev.snippet or '')[:60]}"
        sources = [_src_label(ev.source)] if ev.source else []
        audit.traces.append(ClaimTrace("evidence", claim, sources))
        if not ev.source:
            audit.violations.append(f"evidence '{claim}' has no source (rule 1)")

    return audit


def audit_store(session: Session) -> StoreAudit:
    """Run the grounding audit over every asset in the store."""
    store = StoreAudit()
    for asset_id in session.execute(select(Asset.id).order_by(Asset.created_at)).scalars():
        a = audit_asset(session, asset_id)
        if a is not None:
            store.audits.append(a)
    return store
