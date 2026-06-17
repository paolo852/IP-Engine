"""Run S2+S4+S3 for a profile and corroborate them — the cross-referencing demo.

    python scripts/corroborate_demo.py

Shows two contrasting routings (sprint vs licence-or-park) from the same streams,
all offline (fake S2 client, local corpus, no network/LLM/credentials).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.config import (  # noqa: E402
    load_corroboration_config,
    load_streams_config,
    load_taxonomy_config,
)
from forge.streams.corroboration import corroborate  # noqa: E402
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

PROFILE = profile(
    ["low-power optical interconnect", "edge inference accelerator"],
    problem="Edge-AI interconnects waste energy moving bits between chips",
    solution="A micro-ring modulator photonic interconnect for edge computing",
)
STREAMS_CFG = load_streams_config("config/streams.yaml")
CORRO_CFG = load_corroboration_config("config/corroboration.yaml")
S3 = build_s3_stream(STREAMS_CFG)
S4 = S4TaxonomyStream(load_taxonomy_config("config/taxonomy.yaml"))


def run(s2_client) -> None:
    s2 = S2PatentsStream(s2_client, config=STREAMS_CFG.section("s2_patents")).run(
        PROFILE, publication_id="EP9999999A1", as_of_year=2023
    )
    results = [s2, S4.run(PROFILE), S3.run(PROFILE)]
    print(corroborate(results, CORRO_CFG).explanation())


def main() -> int:
    print("=== Scenario A: rising field, industry citing, moderate crowding ===")
    run(
        FakeS2Client(
            search=SearchResult(total=45, hits=[SearchHit("EP111A1", relevance=0.8)]),
            year_counts=[YearCount(2021, 8), YearCount(2022, 11), YearCount(2023, 15)],
            citing=[CitingDoc("EP900A1", "Acme"), CitingDoc("EP901A1", "BetaCo")],
        )
    )
    print("\n=== Scenario B: strong pull into a crowded field, no citations ===")
    run(
        FakeS2Client(
            search=SearchResult(total=180, hits=[SearchHit("EP222A1", relevance=0.7)]),
            year_counts=[YearCount(2021, 30), YearCount(2022, 33), YearCount(2023, 36)],
            citing=[],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
