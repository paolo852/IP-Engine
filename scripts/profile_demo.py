"""Profile a synthetic asset and show the grounding — the slice-4 demo.

    python scripts/profile_demo.py

Uses a canned (fake) LLM provider so it needs no API key and makes no network
call — it demonstrates the grounding scaffolding, not live model quality. Swap in
``forge.llm.build_provider(load_llm_config(...))`` for a real run (needs creds).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.db.models import Asset, AssetType  # noqa: E402
from forge.enrichment import build_profile  # noqa: E402
from enrichment.fakes import FakeProvider, profile_json  # noqa: E402


def main() -> int:
    asset = Asset(
        asset_type=AssetType.patent,
        source_layer="L1.synthetic",
        title="Low-power photonic interconnect for edge AI accelerators",
        abstract=(
            "A photonic interconnect architecture reducing inter-chip energy per "
            "bit for edge inference workloads (invented; not a real patent)."
        ),
        claims_or_description=(
            "1. An interconnect comprising a micro-ring modulator array coupled "
            "to a silicon waveguide."
        ),
    )

    canned = profile_json(
        problem=("Edge-AI interconnects waste energy moving bits between chips",
                 "reducing inter-chip energy per bit for edge inference workloads"),
        solution=("A micro-ring modulator photonic interconnect",
                  "micro-ring modulator array coupled to a silicon waveguide"),
        applications=[("Edge AI accelerators", "photonic interconnect for edge AI accelerators")],
        query_terms=["optical interconnect energy efficiency", "edge inference hardware"],
    )

    profile = build_profile(asset, FakeProvider(canned, model="demo-model"))

    print(f"model: {profile.model}  prompt: {profile.prompt_version}\n")
    for gf in profile.grounded_fields():
        print(f"# {gf.name}: {gf.value}")
        print(f"  grounded by [{gf.source_field}]: \"{gf.quote}\"\n")
    print("query_terms (problem-space, for later streams):")
    for term in profile.query_terms:
        print(f"  - {term}")
    print("\nevery statement is backed by a verbatim source quote — grounded OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
