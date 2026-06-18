"""End-to-end orchestration: full run, fault isolation, idempotent re-runs."""

from __future__ import annotations

from datetime import date

from forge.pipeline import Pipeline, PipelineConfig
from forge.repository import get_evidence, get_profile, save_asset
from forge.streams.corroboration import Routing
from forge.streams.s1_funding import FundingSearch
from forge.streams.s2_patents import CitingDoc, SearchHit, SearchResult, YearCount

from .enrichment.fakes import FakeProvider, profile_json
from .streams.fakes import FakeS2Client
from .synthetic.assets import minimal_grounded_bundle, synthetic_patent_bundle

AS_OF = date(2025, 1, 1)


def grounded_provider() -> FakeProvider:
    # Quotes are verbatim substrings of the synthetic patent's fields.
    return FakeProvider(
        profile_json(
            problem=("High energy per bit in photonic interconnects",
                     "reducing inter-chip energy per bit for edge inference workloads"),
            solution=("A micro-ring modulator optical interconnect",
                      "micro-ring modulator array coupled to a silicon waveguide"),
            applications=[("Edge AI accelerators", "photonic interconnect for edge AI accelerators")],
            query_terms=["optical interconnect", "edge inference"],
        )
    )


class FakeS1Client:
    def search_funding(self, query, *, years):
        return FundingSearch(total_amount_eur=20_000_000.0, round_count=5,
                             investors=["VC One", "VC Two"])


def fake_s2() -> FakeS2Client:
    return FakeS2Client(
        search=SearchResult(total=45, hits=[SearchHit("EP111A1", relevance=0.8)]),
        year_counts=[YearCount(2022, 8), YearCount(2023, 11), YearCount(2024, 15)],
        citing=[CitingDoc("EP900A1", "Acme"), CitingDoc("EP901A1", "BetaCo")],
    )


def pipeline(provider=None, **clients) -> Pipeline:
    return Pipeline(
        PipelineConfig.from_files(as_of=AS_OF),
        provider or grounded_provider(),
        s2_client=clients.get("s2", fake_s2()),
        s1_client=clients.get("s1", FakeS1Client()),
    )


def test_full_run_persists_and_synthesises(session):
    asset = save_asset(session, synthetic_patent_bundle())
    report = pipeline().run(session, [asset.id])

    r = report.results[0]
    assert r.ok, r.errors
    assert r.dormancy.is_candidate                     # dormant patent
    assert r.profile is not None
    assert r.corroboration.routing in tuple(Routing)   # a routing was produced
    assert r.score.value is not None and 0.0 <= r.score.value <= 1.0
    assert r.brief.ungrounded() == []                  # grounded brief

    # Durable outputs were persisted.
    assert get_profile(session, asset.id) is not None
    streams = {e.stream for e in get_evidence(session, asset.id)}
    assert streams == {"S2_patents", "S4_taxonomy", "S3_roadmaps", "S1_funding"}


def test_profiling_failure_is_isolated(session):
    asset = save_asset(session, synthetic_patent_bundle())
    report = pipeline(provider=FakeProvider("this is not json")).run(session, [asset.id])

    r = report.results[0]
    assert not r.ok
    assert any(e.startswith("profile:") for e in r.errors)
    assert r.profile is None
    assert r.stream_results == []          # streams need a profile -> skipped
    assert r.dormancy is not None          # dormancy still ran
    assert r.brief is not None and r.brief.ungrounded() == []  # brief from asset + dormancy
    assert get_profile(session, asset.id) is None


def test_rerun_is_idempotent(session):
    asset = save_asset(session, synthetic_patent_bundle())
    pipeline().run(session, [asset.id])
    first = len(get_evidence(session, asset.id))

    pipeline().run(session, [asset.id])  # second pass
    assert len(get_evidence(session, asset.id)) == first  # replaced, not duplicated
    assert get_profile(session, asset.id) is not None     # no unique-constraint crash


def test_batch_isolates_a_failing_asset(session):
    patent = save_asset(session, synthetic_patent_bundle())
    dataset = save_asset(session, minimal_grounded_bundle())  # dataset: no dormancy ruleset

    report = pipeline().run(session, [patent.id, dataset.id])
    assert len(report.results) == 2

    by_id = {r.asset_id: r for r in report.results}
    assert by_id[patent.id].ok                       # the good asset completed
    assert not by_id[dataset.id].ok                  # the other failed...
    assert any("dormancy" in e for e in by_id[dataset.id].errors)  # ...but was isolated
