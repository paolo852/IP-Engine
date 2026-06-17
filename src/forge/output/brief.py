"""Market-context brief generator — grounded; zero unsourced sentences.

Every *factual* statement the brief emits carries at least one ``SourceRef`` to a
stored, provenance-backed artifact: an asset field, a profile quote, a stream
evidence record. The brief is composed deterministically from grounded inputs
(no free-form generation), so the invariant holds by construction; ``build_brief``
verifies it and raises ``BriefError`` if any factual statement is unsourced.

Advisory lines (the routing recommendation, the headline score, "no data" notes)
are marked non-factual: they are analysis/explanation, not claims about the
world, and humans decide. They may carry a basis but are not grounding-gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..db.models import Asset
from ..dormancy import DormancyAssessment, Status
from ..enrichment.profiling import AssetProfile, GroundedField
from ..scoring import VentureabilityScore
from ..streams.base import EvidenceRecord, StreamResult


class BriefError(ValueError):
    """Raised when a factual statement would be emitted without a source."""


@dataclass
class SourceRef:
    """A pointer to a stored, provenance-backed source for a statement."""

    kind: str  # "asset_field" | "profile" | "evidence" | "score"
    locator: str
    detail: str = ""
    link: str | None = None


@dataclass
class Statement:
    text: str
    sources: list[SourceRef] = field(default_factory=list)
    factual: bool = True


@dataclass
class BriefSection:
    title: str
    statements: list[Statement] = field(default_factory=list)


@dataclass
class BriefInputs:
    asset: Asset
    profile: AssetProfile | None = None
    dormancy: DormancyAssessment | None = None
    stream_results: list[StreamResult] = field(default_factory=list)
    corroboration: object | None = None  # forge.streams.corroboration.Corroboration
    score: VentureabilityScore | None = None


@dataclass
class MarketContextBrief:
    title: str
    sections: list[BriefSection] = field(default_factory=list)

    def factual_statements(self) -> list[Statement]:
        return [s for sec in self.sections for s in sec.statements if s.factual]

    def ungrounded(self) -> list[Statement]:
        return [s for s in self.factual_statements() if not s.sources]

    def render_markdown(self) -> str:
        lines = [f"# Market-context brief: {self.title}", ""]
        for sec in self.sections:
            if not sec.statements:
                continue
            lines.append(f"## {sec.title}")
            for st in sec.statements:
                if st.factual:
                    cites = "; ".join(_cite(s) for s in st.sources)
                    lines.append(f"- {st.text}  _(sources: {cites})_")
                else:
                    lines.append(f"- _{st.text}_")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _cite(ref: SourceRef) -> str:
    detail = f" — {_truncate(ref.detail)}" if ref.detail else ""
    return f"{ref.kind}:{ref.locator}{detail}"


def _truncate(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _evidence_ref(rec: EvidenceRecord) -> SourceRef:
    return SourceRef(
        kind="evidence",
        locator=f"{rec.source.source_type}:{rec.source.locator}",
        detail=rec.snippet,
        link=rec.link,
    )


def _profile_ref(gf: GroundedField) -> SourceRef:
    return SourceRef(kind="profile", locator=f"asset.{gf.source_field}", detail=gf.quote)


# -- sections ---------------------------------------------------------------
def _asset_section(asset: Asset) -> BriefSection:
    sec = BriefSection("Asset")
    title = asset.title or "(untitled)"
    sec.statements.append(
        Statement(
            f"{asset.asset_type.value} from {asset.source_layer}, titled “{title}”.",
            [SourceRef("asset_field", "asset.title", detail=title)],
        )
    )
    return sec


def _profile_section(profile: AssetProfile) -> BriefSection:
    sec = BriefSection("Problem & solution")
    sec.statements.append(
        Statement(f"Problem: {profile.problem.value}", [_profile_ref(profile.problem)])
    )
    sec.statements.append(
        Statement(f"Solution: {profile.solution.value}", [_profile_ref(profile.solution)])
    )
    for app in profile.applications:
        sec.statements.append(
            Statement(f"Application: {app.value}", [_profile_ref(app)])
        )
    return sec


def _dormancy_section(dormancy: DormancyAssessment) -> BriefSection:
    sec = BriefSection("Dormancy")
    sec.statements.append(
        Statement(
            f"Dormancy verdict: {dormancy.verdict()} (as of {dormancy.as_of.isoformat()}).",
            factual=False,
        )
    )
    for cond in dormancy.conditions:
        if cond.status is Status.UNKNOWN or not cond.field:
            # No usable input -> an explanation, not a grounded claim.
            sec.statements.append(
                Statement(f"{cond.name}: {cond.detail}", factual=False)
            )
        else:
            sec.statements.append(
                Statement(
                    f"{cond.name} [{cond.status.value}]: {cond.detail}",
                    [SourceRef("asset_field", f"asset.{cond.field}", detail=cond.detail)],
                )
            )
    return sec


def _signals_section(stream_results: Iterable[StreamResult]) -> BriefSection:
    sec = BriefSection("Field & market signals")
    for result in stream_results:
        for sig in result.sub_signals:
            if not sig.evidence:
                continue  # can't ground it -> don't claim it
            sec.statements.append(
                Statement(sig.detail or f"{sig.name} = {sig.value:g}",
                          [_evidence_ref(e) for e in sig.evidence])
            )
    return sec


def _corroboration_section(corroboration) -> BriefSection:
    sec = BriefSection("Cross-stream reading")
    sec.statements.append(
        Statement(f"Routing: {corroboration.routing.value} — {corroboration.rationale}",
                  factual=False)
    )
    for conflict in corroboration.conflicts:
        sec.statements.append(Statement(f"Conflict: {conflict}", factual=False))
    return sec


def _scoring_section(score: VentureabilityScore) -> BriefSection:
    sec = BriefSection("Ventureability")
    if score.value is None:
        sec.statements.append(Statement("Ventureability: indeterminate.", factual=False))
    else:
        sec.statements.append(
            Statement(
                f"Ventureability: {score.value:.2f} (coverage {score.coverage:.0%}).",
                factual=False,
            )
        )
    for dim in score.dimensions:
        if not dim.scored:
            sec.statements.append(
                Statement(f"{dim.dimension}: not scored — {dim.rationale}", factual=False)
            )
        else:
            sources = [
                SourceRef("score", dim.dimension, detail=ev) for ev in dim.evidence
            ] or [SourceRef("score", dim.dimension, detail=dim.rationale)]
            sec.statements.append(
                Statement(f"{dim.dimension}: {dim.value:.2f} — {dim.rationale}", sources)
            )
    return sec


def build_brief(inputs: BriefInputs) -> MarketContextBrief:
    """Compose a grounded market-context brief and verify zero unsourced sentences."""
    brief = MarketContextBrief(title=inputs.asset.title or str(inputs.asset.id or "asset"))
    brief.sections.append(_asset_section(inputs.asset))
    if inputs.profile is not None:
        brief.sections.append(_profile_section(inputs.profile))
    if inputs.dormancy is not None:
        brief.sections.append(_dormancy_section(inputs.dormancy))
    if inputs.stream_results:
        brief.sections.append(_signals_section(inputs.stream_results))
    if inputs.corroboration is not None:
        brief.sections.append(_corroboration_section(inputs.corroboration))
    if inputs.score is not None:
        brief.sections.append(_scoring_section(inputs.score))

    verify_grounded(brief)
    return brief


def verify_grounded(brief: MarketContextBrief) -> None:
    """Raise if any factual statement lacks a source (defensive; should not fire)."""
    ungrounded = brief.ungrounded()
    if ungrounded:
        raise BriefError(
            "brief has unsourced factual statements: "
            + "; ".join(s.text for s in ungrounded)
        )
