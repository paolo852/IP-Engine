"""Score a synthetic asset's ventureability with full breakdown — slice-6 demo.

    python scripts/ventureability_demo.py

Runs S2 (fake client) + S4 + S3 for a profile, then computes the transparent,
config-weighted 6-dimension score. No network, no LLM, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.config import load_scoring_config, load_streams_config, load_taxonomy_config  # noqa: E402
from forge.db.models import Asset, AssetType  # noqa: E402
from forge.scoring import ScoringInputs, score_ventureability  # noqa: E402
from forge.streams.s2_patents import (  # noqa: E402
    CitingDoc,
    S2PatentsStream,
    SearchHit,
    SearchResult,
    YearCount,
)
from forge.streams.s3_roadmaps import build_s3_stream  # noqa: E402
from forge.streams.s4_taxonomy import S4TaxonomyStream  # noqa: E402
from streams.fakes import FakeS2Client, profile  # noqa: E402


def main() -> int:
    streams_cfg = load_streams_config("config/streams.yaml")
    prof = profile(
        ["low-power optical interconnect", "edge inference accelerator"],
        problem="Edge-AI interconnects waste energy moving bits between chips",
        solution="A micro-ring modulator photonic interconnect for edge computing",
    )

    s2 = S2PatentsStream(
        FakeS2Client(
            search=SearchResult(total=45, hits=[SearchHit("EP111A1", relevance=0.8)]),
            year_counts=[YearCount(2021, 8), YearCount(2022, 11), YearCount(2023, 15)],
            citing=[CitingDoc("EP900A1", "Acme"), CitingDoc("EP901A1", "BetaCo")],
        ),
        config=streams_cfg.section("s2_patents"),
    ).run(prof, publication_id="EP9999999A1", as_of_year=2023)
    s4 = S4TaxonomyStream(load_taxonomy_config("config/taxonomy.yaml")).run(prof)
    s3 = build_s3_stream(streams_cfg).run(prof)

    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        legal_status="granted",
        key_dates={"grant_date": "2022-06-21"},
    )
    score = score_ventureability(
        ScoringInputs(asset=asset, stream_results=[s2, s3, s4]),
        load_scoring_config("config/scoring.yaml"),
    )
    print(score.breakdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
