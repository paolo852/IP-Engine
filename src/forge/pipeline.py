"""End-to-end orchestration: run the whole method over a batch of assets.

For each asset the pipeline runs, in order: dormancy assessment, LLM profiling
(persisted), the four cross-referencing streams (persisted evidence), cross-stream
corroboration, transparent ventureability scoring, and the grounded brief.

Fault tolerance (rule 7) is the design centre: a failure in one step is captured
and the rest of the asset's pipeline continues where it can; a failure on one
asset never blocks the others. Re-runs are idempotent — the profile and the
streams' evidence are replaced, not duplicated.

The pipeline orchestrates *bought components*: it wires the existing services
together and persists what is durable (profile + evidence); the score, brief, and
corroboration are returned in memory for the committee step (slice 9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Iterable

from sqlalchemy.orm import Session

from .config import (
    CorroborationConfig,
    DormancyConfig,
    OrganisationConfig,
    ScoringConfig,
    StreamsConfig,
    TaxonomyConfig,
    load_corroboration_config,
    load_dormancy_config,
    load_organisation_config,
    load_scoring_config,
    load_streams_config,
    load_taxonomy_config,
)
from .db.models import Asset
from .dormancy import DormancyAssessment, assess_asset
from .enrichment.profiling import AssetProfile, _dedup, build_profile
from .llm.provider import LLMProvider
from .output.brief import BriefInputs, MarketContextBrief, build_brief
from .repository import (
    delete_evidence,
    delete_profile,
    get_asset,
    get_profile,
    save_profile,
    save_score,
    save_stream_result,
    save_synthesis,
)
from .scoring import ScoringInputs, VentureabilityScore, score_ventureability
from .streams.base import StreamResult
from .streams.corroboration import Corroboration, corroborate
from .streams.s1_funding import S1Client, S1FundingStream
from .streams.s2_patents import S2Client, S2PatentsStream
from .streams.s3_roadmaps import build_s3_stream
from .streams.s4_taxonomy import S4TaxonomyStream


@dataclass
class PipelineConfig:
    dormancy: DormancyConfig
    taxonomy: TaxonomyConfig
    corroboration: CorroborationConfig
    scoring: ScoringConfig
    streams: StreamsConfig
    organisation: OrganisationConfig | None = None
    as_of: date | None = None

    @classmethod
    def from_files(cls, *, as_of: date | None = None, config_dir: str = "config") -> "PipelineConfig":
        return cls(
            dormancy=load_dormancy_config(f"{config_dir}/dormancy.yaml"),
            taxonomy=load_taxonomy_config(f"{config_dir}/taxonomy.yaml"),
            corroboration=load_corroboration_config(f"{config_dir}/corroboration.yaml"),
            scoring=load_scoring_config(f"{config_dir}/scoring.yaml"),
            streams=load_streams_config(f"{config_dir}/streams.yaml"),
            organisation=load_organisation_config(f"{config_dir}/organisation.yaml"),
            as_of=as_of,
        )


@dataclass
class AssetPipelineResult:
    asset_id: uuid.UUID
    dormancy: DormancyAssessment | None = None
    profile: AssetProfile | None = None
    stream_results: list[StreamResult] = field(default_factory=list)
    corroboration: Corroboration | None = None
    score: VentureabilityScore | None = None
    brief: MarketContextBrief | None = None
    synthesis: object | None = None  # forge.output.synthesis.DecisionSynthesis
    diagnostics: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class PipelineReport:
    results: list[AssetPipelineResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def summary(self) -> str:
        good = sum(1 for r in self.results if r.ok)
        return f"{len(self.results)} assets: {good} clean, {len(self.results) - good} with errors"


class Pipeline:
    """Wires the services together and runs them, asset by asset, fault-tolerantly."""

    def __init__(
        self,
        config: PipelineConfig,
        provider: LLMProvider,
        *,
        s2_client: S2Client | None = None,
        s1_client: S1Client | None = None,
    ) -> None:
        self.cfg = config
        self.provider = provider
        # S3/S4 are offline (corpus / taxonomy); S2/S1 need an injected client.
        self.s4_stream = S4TaxonomyStream(config.taxonomy)
        self.s3_stream = build_s3_stream(config.streams)
        self.s2_stream = (
            S2PatentsStream(s2_client, config=config.streams.section("s2_patents"))
            if s2_client is not None
            else None
        )
        self.s1_stream = (
            S1FundingStream(s1_client, config=config.streams.section("s1_funding"))
            if s1_client is not None
            else None
        )

    # -- per-asset ----------------------------------------------------------
    def run_asset(self, session: Session, asset: Asset) -> AssetPipelineResult:
        result = AssetPipelineResult(asset_id=asset.id)

        try:
            result.dormancy = assess_asset(
                asset, self.cfg.dormancy, as_of=self.cfg.as_of, org=self.cfg.organisation
            )
        except Exception as exc:  # noqa: BLE001 - isolate the step
            result.errors.append(f"dormancy: {exc}")

        try:
            if get_profile(session, asset.id) is not None:
                delete_profile(session, asset.id)  # idempotent re-run
            profile = build_profile(asset, self.provider)
            save_profile(session, asset, profile)
            result.profile = profile
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            result.errors.append(f"profile: {exc}")

        if result.profile is not None:
            result.stream_results = self._run_streams(asset, result.profile, result.errors)
            try:
                result.diagnostics.extend(
                    self._requery_if_thin(
                        asset, result.profile, result.stream_results, result.errors
                    )
                )
            except Exception as exc:  # noqa: BLE001 - re-query is best-effort
                result.errors.append(f"requery: {exc}")
            try:
                streams_present = {r.stream for r in result.stream_results}
                if streams_present:
                    delete_evidence(session, asset.id, streams=streams_present)
                for stream_result in result.stream_results:
                    save_stream_result(session, asset, stream_result)
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                result.errors.append(f"persist-evidence: {exc}")

        try:
            result.corroboration = corroborate(result.stream_results, self.cfg.corroboration)
            result.score = score_ventureability(
                ScoringInputs(asset, result.stream_results), self.cfg.scoring
            )
            result.brief = build_brief(
                BriefInputs(
                    asset=asset,
                    profile=result.profile,
                    dormancy=result.dormancy,
                    stream_results=result.stream_results,
                    corroboration=result.corroboration,
                    score=result.score,
                )
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"synthesis: {exc}")

        # Persist the engine score so the dashboard and clustering can rank on
        # live output without re-running the pipeline (idempotent: one row/asset).
        if result.score is not None:
            try:
                routing = result.corroboration.routing.value if result.corroboration else None
                save_score(session, asset, result.score, routing=routing)
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                result.errors.append(f"persist-score: {exc}")

        # Decision-oriented synthesis (LLM over the engine's signals). Best-effort:
        # absent without a capable LLM, and a failure never blocks the rest.
        try:
            from .output.synthesis import SynthesisInputs, build_synthesis

            result.synthesis = build_synthesis(
                SynthesisInputs(
                    asset=asset,
                    profile=result.profile,
                    score=result.score,
                    corroboration=result.corroboration,
                    stream_results=result.stream_results,
                    dormancy=result.dormancy,
                ),
                self.provider,
            )
            if result.synthesis is not None:
                save_synthesis(session, asset, result.synthesis)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            result.errors.append(f"synthesis: {exc}")

        return result

    def _run_streams(
        self, asset: Asset, profile: AssetProfile, errors: list[str]
    ) -> list[StreamResult]:
        results: list[StreamResult] = []
        year = (self.cfg.as_of or date.today()).year
        publication_id = _publication_id(asset)

        if self.s2_stream is not None:
            try:
                results.append(
                    self.s2_stream.run(
                        profile,
                        publication_id=publication_id,
                        as_of_year=year,
                        class_codes=getattr(asset, "classification_codes", None),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a failing source must not block others
                errors.append(f"S2: {exc}")
        for name, stream in (("S4", self.s4_stream), ("S3", self.s3_stream)):
            try:
                results.append(stream.run(profile))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        if self.s1_stream is not None:
            try:
                results.append(self.s1_stream.run(profile, as_of_year=year))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"S1: {exc}")
        return results

    def _requery_if_thin(
        self,
        asset: Asset,
        profile: AssetProfile,
        results: list[StreamResult],
        errors: list[str],
    ) -> list[str]:
        """E2: when cross-stream coverage is below the configured floor, re-query
        the live streams (S1/S2) with a BROADENED market-term set, keep whichever
        run gave better coverage, then diagnose *why* coverage is thin — a
        genuinely weak asset vs a profiler that produced poor market queries.

        Returns human-readable diagnostics (also surfaced on the result) so the
        engine logs which case it concluded and why. Mutates ``results`` in place
        when a broadened re-query improves coverage, so the persisted evidence
        reflects the better run. The engine never decides — this only routes the
        asset to human review with a reason (rule 7).
        """
        min_cov = float(self.cfg.streams.sections.get("min_stream_coverage", 0.5))
        cov = _stream_coverage(results)
        # Nothing to re-query against if neither live stream is wired in.
        if self.s1_stream is None and self.s2_stream is None:
            return [f"stream coverage {cov:.0%}; no live stream to re-query"]
        if cov >= min_cov:
            return [f"stream coverage {cov:.0%} (>= {min_cov:.0%} floor; no re-query)"]

        broadened = _broaden_query_terms(profile)
        had_market_terms = any(app.industry_terms for app in profile.applications)

        if not broadened or broadened == list(profile.query_terms):
            # The profiler gave us no wider market vocabulary to try.
            return [
                f"stream coverage {cov:.0%} below {min_cov:.0%} floor; no broader "
                "market terms available — profiler produced poor queries; "
                "insufficient market evidence — human review"
            ]

        # Re-run with the broadened terms; adopt it only if coverage improved so a
        # broader-but-noisier query never makes the evidence worse.
        rerun = self._run_streams(asset, replace(profile, query_terms=broadened), errors)
        new_cov = _stream_coverage(rerun)
        if new_cov > cov:
            results[:] = rerun
            cov = new_cov

        if cov >= min_cov:
            return [
                f"stream coverage rose to {cov:.0%} after broadened market re-query "
                f"(>= {min_cov:.0%} floor)"
            ]

        # Still thin after broadening: distinguish the two failure modes.
        if had_market_terms:
            verdict = (
                "genuinely weak asset — broadened market re-query still found little "
                "signal; insufficient market evidence — human review"
            )
        else:
            verdict = (
                "profiler produced poor queries — no market industry_terms were "
                "generated to search on; sharpen the candidate markets, then re-run"
            )
        return [
            f"stream coverage {cov:.0%} still below {min_cov:.0%} floor after "
            "broadened market re-query",
            verdict,
        ]

    # -- batch --------------------------------------------------------------
    def run(self, session: Session, asset_ids: Iterable[uuid.UUID]) -> PipelineReport:
        report = PipelineReport()
        for asset_id in asset_ids:
            asset = get_asset(session, asset_id)
            if asset is None:
                result = AssetPipelineResult(asset_id=asset_id, errors=["asset not found"])
            else:
                try:
                    result = self.run_asset(session, asset)
                except Exception as exc:  # noqa: BLE001 - one asset never blocks the rest
                    session.rollback()
                    result = AssetPipelineResult(asset_id=asset_id, errors=[f"fatal: {exc}"])
            report.results.append(result)
        return report


def _stream_coverage(results: list[StreamResult]) -> float:
    """Share of the attempted streams that returned at least one evidence record.

    This is the cross-stream *coverage* the re-query gate reasons over: a stream
    that ran but found nothing counts against coverage, which is the honest signal
    that the market queries matched little (E2) — not a fabricated half-score.
    """
    if not results:
        return 0.0
    useful = sum(1 for r in results if r.evidence())
    return useful / len(results)


def _broaden_query_terms(profile: AssetProfile) -> list[str]:
    """A wider MARKET-term set for a re-query (E2).

    The primary queries are each application's ``industry_terms``; when those come
    up thin we broaden to the application *market names*, their *end customers* and
    *use cases* — still market vocabulary, deliberately NOT the patent's technical
    jargon (which finds only the technology, never the market). The original query
    terms are kept too, then the whole set is deduped.
    """
    terms: list[str] = []
    for app in profile.applications:
        terms.extend(app.industry_terms)
        if app.value:
            terms.append(app.value)
        if app.end_customer:
            terms.append(app.end_customer)
        if app.use_case:
            terms.append(app.use_case)
    terms.extend(profile.query_terms)
    return _dedup(terms)


def _publication_id(asset: Asset) -> str | None:
    """The asset's EPO publication id, from its epo_ops field provenance (if any)."""
    for link in getattr(asset, "provenance", []) or []:
        if link.source.source_type == "epo_ops":
            return link.source.locator
    return None
