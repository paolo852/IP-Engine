"""Cluster a scored pipeline into sector portfolios — the slice-7 demo.

    python scripts/clustering_demo.py

Pure, deterministic clustering — no DB, no network, no model.
"""

from __future__ import annotations

from forge.clustering import ClusterInput, cluster_assets
from forge.config import load_sectors_config

# A small scored "pipeline": (id, profile text, ventureability).
PIPELINE = [
    ("EP-A", "Low-power photonic optical waveguide interconnect for edge AI", 0.85),
    ("EP-B", "Silicon photonics modulator for data-centre links", 0.71),
    ("EP-C", "Edge AI inference accelerator semiconductor chip", 0.78),
    ("EP-D", "Green hydrogen electrolyser with improved fuel cell", 0.52),
    ("EP-E", "Advanced composite coating and catalyst for turbines", 0.40),
    ("EP-F", "A generic mechanical fastener", 0.20),
]


def main() -> int:
    config = load_sectors_config("config/sectors.yaml")
    inputs = [
        ClusterInput(asset_id=aid, title=aid, text=text, ventureability=score)
        for aid, text, score in PIPELINE
    ]
    result = cluster_assets(inputs, config)

    print(f"clusters — {result.summary()}\n")
    for cluster in result.clusters:
        mean = f"{cluster.mean_score:.2f}" if cluster.mean_score is not None else "n/a"
        print(f"## {cluster.label}  ({cluster.size} assets, mean {mean})")
        for m in cluster.members:
            score = f"{m.ventureability:.2f}" if m.ventureability is not None else "  - "
            terms = f"  [{', '.join(m.matched_terms)}]" if m.matched_terms else ""
            print(f"   {score}  {m.asset_id}{terms}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
