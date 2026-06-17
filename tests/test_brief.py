"""Market-context brief: composed deterministically, zero unsourced sentences."""

from __future__ import annotations

from datetime import date

import pytest

from forge.config import (
    load_corroboration_config,
    load_dormancy_config,
    load_organisation_config,
    load_scoring_config,
)
from forge.db.models import Asset, AssetType, Licence
from forge.dormancy import assess_asset
from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.output import BriefInputs, BriefSection, MarketContextBrief, Statement, build_brief
from forge.output.brief import BriefError, verify_grounded
from forge.scoring import ScoringInputs, score_ventureability
from forge.streams.base import EvidenceRecord, SourceSpec, StreamResult, SubSignal
from forge.streams.corroboration import corroborate

AS_OF = date(2025, 1, 1)


def ev(stream, snippet):
    return EvidenceRecord(stream, 0.6, snippet, SourceSpec("x", Licence.public, "loc"))


def sub(name, value, evs=()):
    return SubSignal(name=name, value=value, detail=f"{name}={value:g}", evidence=list(evs))


def sr(stream, *subs):
    return StreamResult(stream=stream, sub_signals=list(subs))


def asset() -> Asset:
    return Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="Low-power photonic interconnect",
        abstract="reducing inter-chip energy per bit for edge inference",
        claims_or_description="a micro-ring modulator array coupled to a silicon waveguide",
        legal_status="granted",
        key_dates={"filing_date": "2020-01-01", "grant_date": "2022-06-21"},
        fee_status="lapsing",
        encumbrances="none recorded",
        owners=["Synthetic Research Org"],
    )


def profile() -> AssetProfile:
    def g(name, value, quote, field):
        return GroundedField(name=name, value=value, quote=quote, source_field=field)

    return AssetProfile(
        problem=g("problem", "High energy per bit in interconnects",
                  "reducing inter-chip energy per bit", "abstract"),
        solution=g("solution", "Micro-ring modulator interconnect",
                   "micro-ring modulator array", "claims_or_description"),
        applications=[g("application[0]", "Edge AI", "photonic interconnect", "title")],
        query_terms=["optical interconnect"],
        model="m",
    )


def streams():
    return [
        sr("S2_patents",
           sub("filing_trend_slope", 3.0, [ev("S2_patents", "Filings 2021-2023 slope +3/yr")]),
           sub("forward_citation_count", 2.0, [ev("S2_patents", "EP9 cites EPX")]),
           sub("neighbour_density", 40.0, [ev("S2_patents", "Neighbouring EP1")])),
        sr("S3_roadmaps", sub("industrial_regulatory_pull", 4.0, [ev("S3_roadmaps", "roadmap: Photonics")])),
        sr("S4_taxonomy", sub("eu_taxonomy:digital", 5.0, [ev("S4_taxonomy", "Aligns with EU digital")])),
    ]


def full_inputs() -> BriefInputs:
    a = asset()
    results = streams()
    return BriefInputs(
        asset=a,
        profile=profile(),
        dormancy=assess_asset(
            a, load_dormancy_config("config/dormancy.yaml"), as_of=AS_OF,
            org=load_organisation_config("config/organisation.yaml"),
        ),
        stream_results=results,
        corroboration=corroborate(results, load_corroboration_config("config/corroboration.yaml")),
        score=score_ventureability(ScoringInputs(a, results), load_scoring_config("config/scoring.yaml")),
    )


def test_full_brief_has_zero_unsourced_sentences():
    brief = build_brief(full_inputs())
    assert brief.ungrounded() == []
    assert brief.factual_statements()  # there are factual statements
    assert all(s.sources for s in brief.factual_statements())


def test_brief_sections_present():
    brief = build_brief(full_inputs())
    titles = [sec.title for sec in brief.sections]
    assert titles == [
        "Asset", "Problem & solution", "Dormancy",
        "Field & market signals", "Cross-stream reading", "Ventureability",
    ]


def test_profile_statement_cites_its_grounded_quote():
    brief = build_brief(full_inputs())
    problem = next(
        s for sec in brief.sections for s in sec.statements if s.text.startswith("Problem:")
    )
    src = problem.sources[0]
    assert src.kind == "profile" and src.locator == "asset.abstract"
    assert "inter-chip energy" in src.detail


def test_signal_statements_cite_evidence_records():
    brief = build_brief(full_inputs())
    sec = next(s for s in brief.sections if s.title == "Field & market signals")
    assert sec.statements
    assert any(
        src.kind == "evidence" and src.locator.startswith("x:")
        for st in sec.statements for src in st.sources
    )


def test_render_markdown_includes_title_and_citations():
    md = build_brief(full_inputs()).render_markdown()
    assert md.startswith("# Market-context brief: Low-power photonic interconnect")
    assert "Problem:" in md and "_(sources:" in md


def test_minimal_brief_with_only_asset_is_still_grounded():
    brief = build_brief(BriefInputs(asset=asset()))
    assert [sec.title for sec in brief.sections] == ["Asset"]
    assert brief.ungrounded() == []


def test_verify_rejects_an_unsourced_factual_statement():
    bad = MarketContextBrief(
        title="x",
        sections=[BriefSection("S", [Statement("an unsourced claim", [], factual=True)])],
    )
    with pytest.raises(BriefError, match="unsourced factual"):
        verify_grounded(bad)


def test_advisory_lines_are_not_grounding_gated():
    brief = build_brief(full_inputs())
    # The routing line and indeterminate dimensions are advisory (non-factual).
    advisory = [s for sec in brief.sections for s in sec.statements if not s.factual]
    assert any("Routing:" in s.text for s in advisory)
    assert any("capital_intensity: not scored" in s.text for s in advisory)
