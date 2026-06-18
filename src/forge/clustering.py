"""L4 sector clustering — deterministic, config-driven portfolio grouping.

Groups scored assets into sectors using a config-defined sector taxonomy, so the
committee sees ranked portfolios by theme instead of a flat list. There is NO
black-box ML: each asset is assigned to its best-matching sector by transparent,
word-boundary term overlap, and every membership records exactly which terms
placed it there. Assets matching no sector land in an explicit ``unclassified``
bucket. Ties go to the earlier sector in config order, so results are stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import SectorsConfig

UNCLASSIFIED = "unclassified"


@dataclass
class ClusterInput:
    """One asset's clustering inputs (decoupled from DB/profile types)."""

    asset_id: object
    title: str | None
    text: str
    ventureability: float | None = None


@dataclass
class ClusterMember:
    asset_id: object
    title: str | None
    ventureability: float | None
    matched_terms: list[str]


@dataclass
class SectorCluster:
    sector_id: str
    label: str
    members: list[ClusterMember] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def mean_score(self) -> float | None:
        scored = [m.ventureability for m in self.members if m.ventureability is not None]
        return sum(scored) / len(scored) if scored else None


@dataclass
class ClusteringResult:
    clusters: list[SectorCluster] = field(default_factory=list)

    def sector(self, sector_id: str) -> SectorCluster | None:
        return next((c for c in self.clusters if c.sector_id == sector_id), None)

    def assignment(self) -> dict:
        return {m.asset_id: c.sector_id for c in self.clusters for m in c.members}

    def summary(self) -> str:
        return "; ".join(f"{c.label}: {c.size}" for c in self.clusters)


def _term_pattern(term: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in term.lower().split())
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


def cluster_assets(
    inputs: list[ClusterInput], config: SectorsConfig
) -> ClusteringResult:
    """Assign each asset to its best-matching sector; rank members by venture score."""
    order = [s.id for s in config.sectors]
    patterns = {
        s.id: [(t, _term_pattern(t)) for t in s.terms] for s in config.sectors
    }
    buckets = {s.id: SectorCluster(s.id, s.label) for s in config.sectors}
    buckets[UNCLASSIFIED] = SectorCluster(UNCLASSIFIED, "Unclassified")

    for inp in inputs:
        text = inp.text.lower()
        best_id: str | None = None
        best_matched: list[str] = []
        for sid in order:
            matched = [t for t, pat in patterns[sid] if pat.search(text)]
            if len(matched) > len(best_matched):  # strict: first sector wins ties
                best_id, best_matched = sid, matched

        if best_id is not None and len(best_matched) >= config.min_terms:
            buckets[best_id].members.append(
                ClusterMember(inp.asset_id, inp.title, inp.ventureability, best_matched)
            )
        else:
            buckets[UNCLASSIFIED].members.append(
                ClusterMember(inp.asset_id, inp.title, inp.ventureability, [])
            )

    for cluster in buckets.values():
        cluster.members.sort(
            key=lambda m: (m.ventureability is None, -(m.ventureability or 0.0))
        )

    # Emit non-empty sectors in config order, then unclassified (if any).
    clusters = [buckets[sid] for sid in order if buckets[sid].members]
    if buckets[UNCLASSIFIED].members:
        clusters.append(buckets[UNCLASSIFIED])
    return ClusteringResult(clusters=clusters)


def cluster_input(asset, *, profile=None, ventureability: float | None = None) -> ClusterInput:
    """Build a ClusterInput from an asset (+ optional profile/score).

    Text comes from the profile (problem/solution/applications/query_terms) when
    available, else the asset's own title + abstract.
    """
    if profile is not None:
        parts = [profile.problem.value, profile.solution.value]
        parts += [a.value for a in profile.applications]
        parts += list(profile.query_terms)
        text = " ".join(parts)
    else:
        text = " ".join(p for p in (asset.title, asset.abstract) if p)
    return ClusterInput(
        asset_id=asset.id, title=asset.title, text=text, ventureability=ventureability
    )
