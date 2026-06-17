"""Retrieve roadmaps/standards for a synthetic profile — the S3 demo.

    python scripts/stream_s3_demo.py

Deterministic TF-IDF retrieval over the curated corpus — no network, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.config import load_streams_config  # noqa: E402
from forge.streams.s3_roadmaps import build_s3_stream  # noqa: E402
from streams.fakes import profile  # noqa: E402


def main() -> int:
    s3 = build_s3_stream(load_streams_config("config/streams.yaml"))
    result = s3.run(
        profile(
            ["low-power optical interconnect", "edge inference accelerator"],
            problem="Edge-AI interconnects waste energy moving bits between chips",
            solution="A micro-ring modulator photonic interconnect for edge computing",
        )
    )

    sig = result.signal("industrial_regulatory_pull")
    if sig is None:
        print("no industrial/regulatory pull found")
        return 0
    print(f"# industrial_regulatory_pull = {sig.value:g}\n")
    for ev in sig.evidence:
        print(f"  [{ev.match_strength:.2f}] {ev.snippet}")
        if ev.link:
            print(f"          {ev.link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
