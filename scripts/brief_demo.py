"""Generate a grounded market-context brief for a synthetic asset — slice-8 demo.

    python scripts/brief_demo.py

Runs the whole pipeline offline (profile + dormancy + S2/S4/S3 + corroboration +
score), then composes the brief and prints it. Every factual line is sourced.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.config import (  # noqa: E402
    load_corroboration_config,
    load_dormancy_config,
    load_organisation_config,
    load_scoring_config,
    load_streams_config,
    load_taxonomy_config,
)
from forge.db.models import Asset, AssetType  # noqa: E402
from forge.dormancy import assess_asset  # noqa: E402
from forge.enrichment.profiling import AssetProfile, GroundedField  # noqa: E402
from forge.output import BriefInputs, build_brief  # noqa: E402
from forge.scoring import ScoringInputs, score_ventureability  # noqa: E402
from forge.streams.corroboration import corroborate  # noqa: E402
from forge.streams.s2_patents import (  # noqa: E402
    CitingDoc, S2PatentsStream, SearchHit, SearchResult, YearCount,
)
from forge.streams.s3_roadmaps import build_s3_stream  # noqa: E402
from forge.streams.s4_taxonomy import S4TaxonomyStream  # noqa: E402
from streams.fakes import FakeS2Client, profile  # noqa: E402


def main() -> int:
    streams_cfg = load_streams_config("config/streams.yaml")
    prof_terms = profile(
        ["low-power optical interconnect", "edge inference accelerator"],
        problem="Edge-AI interconnects waste energy moving bits between chips",
        solution="A micro-ring modulator photonic interconnect for edge computing",
    )

    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="Low-power photonic interconnect for edge AI accelerators",
        abstract="A photonic interconnect reducing inter-chip energy per bit for edge inference",
        claims_or_description="a micro-ring modulator array coupled to a silicon waveguide",
        legal_status="granted",
        key_dates={"filing_date": "2020-01-01", "grant_date": "2022-06-21"},
        fee_status="lapsing",
        encumbrances="none recorded",
        owners=["Synthetic Research Org"],
    )

    # A grounded profile (quotes are verbatim substrings of the asset text above).
    grounded = AssetProfile(
        problem=GroundedField("problem", "Edge-AI interconnects waste energy per bit",
                              "reducing inter-chip energy per bit", "abstract"),
        solution=GroundedField("solution", "Micro-ring modulator photonic interconnect",
                               "micro-ring modulator array coupled to a silicon waveguide",
                               "claims_or_description"),
        applications=[GroundedField("application[0]", "Edge AI accelerators",
                                    "photonic interconnect for edge AI accelerators", "title")],
        query_terms=["optical interconnect", "edge inference"],
        model="demo-model",
    )

    s2 = S2PatentsStream(
        FakeS2Client(
            search=SearchResult(total=45, hits=[SearchHit("EP111A1", relevance=0.8)]),
            year_counts=[YearCount(2021, 8), YearCount(2022, 11), YearCount(2023, 15)],
            citing=[CitingDoc("EP900A1", "Acme"), CitingDoc("EP901A1", "BetaCo")],
        ),
        config=streams_cfg.section("s2_patents"),
    ).run(prof_terms, publication_id="EP9999999A1", as_of_year=2023)
    s4 = S4TaxonomyStream(load_taxonomy_config("config/taxonomy.yaml")).run(prof_terms)
    s3 = build_s3_stream(streams_cfg).run(prof_terms)
    results = [s2, s3, s4]

    brief = build_brief(
        BriefInputs(
            asset=asset,
            profile=grounded,
            dormancy=assess_asset(
                asset, load_dormancy_config("config/dormancy.yaml"), as_of=date(2025, 1, 1),
                org=load_organisation_config("config/organisation.yaml"),
            ),
            stream_results=results,
            corroboration=corroborate(results, load_corroboration_config("config/corroboration.yaml")),
            score=score_ventureability(ScoringInputs(asset, results), load_scoring_config("config/scoring.yaml")),
        )
    )

    print(brief.render_markdown())
    print(f"(unsourced factual sentences: {len(brief.ungrounded())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
