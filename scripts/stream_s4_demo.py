"""Classify a synthetic profile against the EU taxonomy — the S4 demo.

    python scripts/stream_s4_demo.py

Pure, deterministic classification — no network, no LLM, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.config import load_taxonomy_config  # noqa: E402
from forge.streams.s4_taxonomy import S4TaxonomyStream  # noqa: E402
from streams.fakes import profile  # noqa: E402


def main() -> int:
    p = profile(
        ["low-power optical interconnect", "edge inference accelerator"],
        problem="Edge-AI interconnects waste energy moving bits between chips",
        solution="A micro-ring modulator photonic interconnect for edge computing",
        applications=("artificial intelligence accelerators", "data analytics hardware"),
    )
    result = S4TaxonomyStream(load_taxonomy_config("config/taxonomy.yaml")).run(p)

    if not result.sub_signals:
        print("no EU-taxonomy alignment found")
        return 0
    for sig in result.sub_signals:
        ev = sig.evidence[0]
        print(f"# {sig.name}  (strength {ev.match_strength:.2f})")
        print(f"  {sig.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
