"""Run the S1 (funding flows) stream over canned data — the S1 demo.

    python scripts/stream_s1_demo.py

Uses a fake Dealroom client (no licence key, no network). Only DERIVED aggregates
are emitted as evidence; raw rounds never leave the stream.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.streams.s1_funding import FundingSearch, S1FundingStream  # noqa: E402
from streams.fakes import profile  # noqa: E402


class FakeS1Client:
    def search_funding(self, query, *, years):
        return FundingSearch(
            total_amount_eur=45_000_000.0,
            round_count=8,
            investors=["VC One", "VC Two", "Growth Fund", "Sovereign Tech Fund"],
        )


def main() -> int:
    stream = S1FundingStream(FakeS1Client(), config={"funding_window_years": 3, "max_investors": 5})
    result = stream.run(
        profile(["low-power optical interconnect", "edge inference accelerator"]),
        as_of_year=2023,
    )
    for sig in result.sub_signals:
        print(f"# {sig.name} = {sig.value:g}\n  {sig.detail}")
    print(f"\nnormalised evidence records (all licensed-dealroom, derived only): {len(result.evidence())}")
    for ev in result.evidence():
        print(f"  [{ev.source.licence.value}] {ev.snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
