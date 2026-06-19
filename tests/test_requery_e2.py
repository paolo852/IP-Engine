"""E2: low-coverage re-query — broaden market terms, then diagnose *why* thin.

Covers the pure helpers (`_stream_coverage`, `_broaden_query_terms`), the
`_requery_if_thin` decision (adopt a better broadened run; distinguish a
genuinely weak asset from a profiler that produced poor queries), and the
web-side read-time review reason that surfaces the same distinction.
"""

from __future__ import annotations

from datetime import date

from forge.db.models import Licence
from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.pipeline import (
    Pipeline,
    PipelineConfig,
    _broaden_query_terms,
    _stream_coverage,
)
from forge.repository import save_asset
from forge.streams.base import EvidenceRecord, SourceSpec, StreamResult, SubSignal

from .synthetic.assets import synthetic_patent_bundle
from .test_pipeline import FakeS1Client, fake_s2, grounded_provider

AS_OF = date(2025, 1, 1)


# -- builders ---------------------------------------------------------------
def _useful(stream: str) -> StreamResult:
    rec = EvidenceRecord(
        stream=stream,
        match_strength=0.5,
        snippet="x",
        source=SourceSpec(source_type=stream, licence=Licence.public, locator="loc"),
    )
    return StreamResult(stream=stream, sub_signals=[SubSignal("n", 1.0, "d", [rec])])


def _empty(stream: str) -> StreamResult:
    return StreamResult(stream=stream, sub_signals=[])


def _profile(*, industry_terms: list[str]) -> AssetProfile:
    app = GroundedField(
        name="application[0]",
        value="quality control in semiconductor fabs",
        quote="q",
        end_customer="fab operators",
        use_case="inline defect scanning",
        industry_terms=industry_terms,
    )
    return AssetProfile(
        problem=GroundedField("problem", "p", "q"),
        solution=GroundedField("solution", "s", "q"),
        applications=[app],
        query_terms=list(industry_terms),  # primary == the market terms
        model="m",
    )


def _pipeline() -> Pipeline:
    return Pipeline(
        PipelineConfig.from_files(as_of=AS_OF),
        grounded_provider(),
        s2_client=fake_s2(),
        s1_client=FakeS1Client(),
    )


# -- pure helpers -----------------------------------------------------------
def test_stream_coverage_counts_streams_with_evidence():
    assert _stream_coverage([]) == 0.0
    quarter = [_useful("S2"), _empty("S1"), _empty("S3"), _empty("S4")]
    assert _stream_coverage(quarter) == 0.25
    assert _stream_coverage([_useful("S2"), _useful("S1")]) == 1.0


def test_broaden_adds_market_language_and_dedups():
    prof = _profile(industry_terms=["wafer inspection", "defect metrology"])
    broad = _broaden_query_terms(prof)

    # broadened to the application's market name, end customer and use case...
    assert "quality control in semiconductor fabs" in broad
    assert "fab operators" in broad
    assert "inline defect scanning" in broad
    # ...while keeping the primary terms, and strictly wider than them
    assert "wafer inspection" in broad
    assert set(broad) > set(prof.query_terms)
    # deduped (case-insensitive)
    assert len(broad) == len({t.lower() for t in broad})


# -- the re-query decision --------------------------------------------------
def test_requery_adopts_broadened_run_when_coverage_improves():
    pl = _pipeline()
    prof = _profile(industry_terms=["wafer inspection"])
    thin = [_useful("S3"), _empty("S2"), _empty("S1"), _empty("S4")]  # 25%

    captured: dict = {}

    def fake_run(asset, profile, errors):
        captured["terms"] = list(profile.query_terms)
        return [_useful("S2"), _useful("S1"), _useful("S3"), _useful("S4")]  # 100%

    pl._run_streams = fake_run
    diags = pl._requery_if_thin(None, prof, thin, [])

    assert any("rose to" in d for d in diags)
    assert all(r.evidence() for r in thin)  # in-place adoption of the better run
    assert "fab operators" in captured["terms"]  # broadened terms were used


def test_requery_flags_genuinely_weak_when_market_terms_present():
    pl = _pipeline()
    prof = _profile(industry_terms=["wafer inspection"])  # market terms exist
    thin = [_useful("S3"), _empty("S2"), _empty("S1"), _empty("S4")]
    # re-query still finds nothing more
    pl._run_streams = lambda a, p, e: [_useful("S3"), _empty("S2"), _empty("S1"), _empty("S4")]

    diags = pl._requery_if_thin(None, prof, thin, [])
    assert any("genuinely weak" in d for d in diags)
    assert any("human review" in d for d in diags)


def test_requery_flags_poor_queries_when_no_market_terms():
    pl = _pipeline()
    prof = _profile(industry_terms=[])  # no market terms, but value/customer broaden
    thin = [_useful("S3"), _empty("S2"), _empty("S1"), _empty("S4")]
    pl._run_streams = lambda a, p, e: [_useful("S3"), _empty("S2"), _empty("S1"), _empty("S4")]

    diags = pl._requery_if_thin(None, prof, thin, [])
    assert any("poor queries" in d for d in diags)


def test_good_run_records_a_coverage_diagnostic(session):
    asset = save_asset(session, synthetic_patent_bundle())
    r = _pipeline().run(session, [asset.id]).results[0]
    assert r.ok, r.errors
    assert r.diagnostics and any("coverage" in d for d in r.diagnostics)


# -- web read-time review reason -------------------------------------------
def test_review_reason_distinguishes_failure_modes():
    from types import SimpleNamespace

    from forge.web.app import _review_reason

    assert _review_reason(SimpleNamespace(candidate_applications=[]), False) is None

    weak = _review_reason(
        SimpleNamespace(candidate_applications=[{"industry_terms": ["x"]}]), True
    )
    assert "genuinely weak" in weak

    poor = _review_reason(
        SimpleNamespace(candidate_applications=[{"industry_terms": []}]), True
    )
    assert "no market" in poor.lower()

    # no profile at all -> still a poor-queries reason, never a crash
    assert "no market" in _review_reason(None, True).lower()
