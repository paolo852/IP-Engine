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
from sqlalchemy.orm import Session, selectinload

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
    # Store-wide, non-per-asset violations: licence separation + graph grounding.
    store_violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.audits) and not self.store_violations

    @property
    def claim_count(self) -> int:
        return sum(a.claim_count for a in self.audits)

    def violations(self) -> list[str]:
        asset = [f"{a.title or a.asset_id}: {v}" for a in self.audits for v in a.violations]
        return asset + list(self.store_violations)

    def summary(self) -> str:
        grounded = sum(a.grounded_count for a in self.audits)
        viol = sum(len(a.violations) for a in self.audits) + len(self.store_violations)
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
        if self.store_violations:
            lines.append("store-wide (licence separation / graph grounding):")
            for v in self.store_violations:
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

    # 4. Need hypotheses — an emitted (falsifiable) sentence must trace to the
    #    grounding pointer it was derived from (the graph tie), rules 1 & 4.
    from ..matching import get_need_hypotheses

    for h in get_need_hypotheses(session, asset.id):
        refs = [
            str(e["ref"])
            for e in (h.evidence or [])
            if isinstance(e, dict) and e.get("ref")
        ]
        claim = f"{h.track.value} need: {h.company.name}"
        audit.traces.append(ClaimTrace("hypothesis", claim, refs))
        if not refs:
            audit.violations.append(
                f"need hypothesis for '{h.company.name}' has no source pointer (rule 1)"
            )

    return audit


def licence_separation_audit(session: Session) -> list[str]:
    """Rule 5/7: licensed RAW data must never back an asset's factual fields.

    Licensed sources (Dealroom/PATSTAT) may only ground DERIVED signals (Evidence)
    — storing an asset fact grounded directly to a licensed source would republish
    licensed raw. Any such field provenance is a violation.
    """
    from ..db.models import FieldProvenance, Licence

    licensed = {Licence.licensed_dealroom, Licence.licensed_patstat}
    out: list[str] = []
    stmt = select(FieldProvenance).options(selectinload(FieldProvenance.source))
    for fp in session.execute(stmt).scalars():
        if fp.source is not None and fp.source.licence in licensed:
            out.append(
                f"asset {fp.asset_id} field '{fp.field_name}' is grounded to a LICENSED "
                f"raw source ({_src_label(fp.source)}, {fp.source.licence.value}) — licensed "
                "raw must back only derived signals, never asset facts (rule 5)"
            )
    return out


def graph_grounding_audit(session: Session) -> list[str]:
    """Rule 1 for the graph: a public/registered relationship (source_layer 0/1)
    must carry a source pointer. Tacit (layer 2) ties are entered by a person and
    are exempt from a source_ref."""
    from ..db.models import Relationship

    out: list[str] = []
    for rel in session.execute(select(Relationship)).scalars():
        if rel.source_layer in (0, 1) and not rel.source_ref:
            out.append(
                f"relationship {rel.id} (company {rel.company_id}, layer {rel.source_layer}) "
                "has no source_ref — a public/registered graph tie must be grounded (rule 1)"
            )
    return out


def audit_store(session: Session) -> StoreAudit:
    """Run the full governance audit: per-asset grounding (incl. need hypotheses),
    plus store-wide licence-separation and graph-grounding checks (T16)."""
    store = StoreAudit()
    for asset_id in session.execute(select(Asset.id).order_by(Asset.created_at)).scalars():
        a = audit_asset(session, asset_id)
        if a is not None:
            store.audits.append(a)
    store.store_violations.extend(licence_separation_audit(session))
    store.store_violations.extend(graph_grounding_audit(session))
    return store
