"""Run the S2 (patents/citations) stream over canned data — the slice-5 demo.

    python scripts/stream_s2_demo.py

Uses a fake S2 client (no OPS credentials, no network). Swap in
``OpsS2Client(OpsClient(...))`` for a live run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.streams.s2_patents import (  # noqa: E402
    CitingDoc,
    S2PatentsStream,
    SearchHit,
    SearchResult,
    YearCount,
)
from streams.fakes import FakeS2Client, profile  # noqa: E402


def main() -> int:
    client = FakeS2Client(
        search=SearchResult(
            total=128,
            hits=[
                SearchHit("EP3101010A1", "Photonic interconnect", 0.91),
                SearchHit("EP3202020A1", "On-chip optical link", 0.84),
            ],
        ),
        year_counts=[
            YearCount(2019, 6), YearCount(2020, 9), YearCount(2021, 11),
            YearCount(2022, 14), YearCount(2023, 18),
        ],
        citing=[
            CitingDoc("EP3909090A1", entity="Acme Photonics"),
            CitingDoc("EP3808080B1", entity="EdgeCompute Ltd"),
        ],
    )
    stream = S2PatentsStream(client, config={"filing_window_years": 5, "max_neighbours": 10})
    result = stream.run(
        profile(["low-power optical interconnect", "edge inference accelerator"]),
        publication_id="EP9999999A1",
        as_of_year=2023,
    )

    for sig in result.sub_signals:
        print(f"# {sig.name} = {sig.value:g}")
        print(f"  {sig.detail}")
    print(f"\nnormalised evidence records: {len(result.evidence())}")
    for rec in result.evidence()[:4]:
        print(f"  [{rec.match_strength:.2f}] {rec.snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
