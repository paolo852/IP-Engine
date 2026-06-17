"""Cross-stream corroboration — the core of L3 cross-referencing.

Cross-referencing is *corroboration analysis*, NOT averaging four numbers. This
module reads the sub-signals from the streams (S2/S3/S4), turns each into a
qualitative INDICATOR via config thresholds, then looks for AGREEMENT vs CONFLICT
across them to emit a routing signal:

* corroborating positive signals across streams  -> SPRINT
* the spec's conflict (market/regulatory pull into a crowded field, yet no
  forward citations of THIS asset)               -> LICENCE_OR_PARK
* a single positive signal                        -> WATCH
* nothing favourable / declining                  -> PARK

Every verdict is explainable: it carries the indicators (level + basis), the
agreements, and the conflicts that drove it. It feeds scoring + the brief; it
does not decide an asset's fate.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable

from ..config import CorroborationConfig
from .base import StreamResult


class Routing(str, enum.Enum):
    SPRINT = "sprint"
    LICENCE_OR_PARK = "licence_or_park"
    WATCH = "watch"
    PARK = "park"


@dataclass
class Indicator:
    """A qualitative reading derived from one or more stream sub-signals."""

    name: str
    level: str
    basis: str
    favourable: bool = False


@dataclass
class Corroboration:
    routing: Routing
    rationale: str
    indicators: list[Indicator] = field(default_factory=list)
    agreements: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def indicator(self, name: str) -> Indicator | None:
        return next((i for i in self.indicators if i.name == name), None)

    def explanation(self) -> str:
        lines = [f"routing: {self.routing.value} — {self.rationale}"]
        for ind in self.indicators:
            mark = "+" if ind.favourable else " "
            lines.append(f"  [{mark}] {ind.name}: {ind.level} ({ind.basis})")
        for conflict in self.conflicts:
            lines.append(f"  CONFLICT: {conflict}")
        return "\n".join(lines)


def _signal_value(results: Iterable[StreamResult], name: str) -> float | None:
    for result in results:
        sig = result.signal(name)
        if sig is not None:
            return sig.value
    return None


def _has_signal_prefix(results: Iterable[StreamResult], prefix: str) -> bool:
    return any(s.name.startswith(prefix) for r in results for s in r.sub_signals)


def _field_momentum(results, cfg: dict) -> Indicator:
    slope = _signal_value(results, "filing_trend_slope")
    if slope is None:
        return Indicator("field_momentum", "unknown", "no filing-trend data")
    if slope >= cfg["rising_min_slope"]:
        return Indicator("field_momentum", "rising", f"slope {slope:+.2f}/yr", True)
    if slope <= cfg["declining_max_slope"]:
        return Indicator("field_momentum", "declining", f"slope {slope:+.2f}/yr")
    return Indicator("field_momentum", "flat", f"slope {slope:+.2f}/yr")


def _industry_attention(results, cfg: dict) -> Indicator:
    cites = _signal_value(results, "forward_citation_count")
    if cites is None:
        return Indicator("industry_attention", "unknown", "no citation data")
    n = int(cites)
    if n >= cfg["strong_min"]:
        return Indicator("industry_attention", "strong", f"{n} forward citations", True)
    if n >= cfg["some_min"]:
        return Indicator("industry_attention", "some", f"{n} forward citations", True)
    return Indicator("industry_attention", "none", "0 forward citations")


def _field_crowding(results, cfg: dict) -> Indicator:
    density = _signal_value(results, "neighbour_density")
    if density is None:
        return Indicator("field_crowding", "unknown", "no neighbour data")
    n = int(density)
    if n >= cfg["crowded_min"]:
        return Indicator("field_crowding", "crowded", f"{n} neighbouring patents")
    if n >= cfg["moderate_min"]:
        return Indicator("field_crowding", "moderate", f"{n} neighbouring patents")
    return Indicator("field_crowding", "sparse", f"{n} neighbouring patents")


def _market_pull(results, cfg: dict) -> Indicator:
    pull = _signal_value(results, "industrial_regulatory_pull")
    n = int(pull) if pull is not None else 0
    if n >= cfg["strong_min"]:
        return Indicator("market_pull", "strong", f"{n} roadmap/standard matches", True)
    if n >= cfg["weak_min"]:
        return Indicator("market_pull", "weak", f"{n} roadmap/standard matches", True)
    return Indicator("market_pull", "none", "no roadmap/standard matches")


def _eu_alignment(results) -> Indicator:
    aligned = _has_signal_prefix(results, "eu_taxonomy:")
    if aligned:
        return Indicator("eu_alignment", "aligned", "matches an EU-priority category", True)
    return Indicator("eu_alignment", "none", "no EU-taxonomy alignment")


def corroborate(
    results: Iterable[StreamResult], config: CorroborationConfig
) -> Corroboration:
    """Synthesise stream results into an explainable routing signal."""
    results = list(results)
    ind = {
        "field_momentum": _field_momentum(results, config.indicator("field_momentum")),
        "industry_attention": _industry_attention(
            results, config.indicator("industry_attention")
        ),
        "field_crowding": _field_crowding(results, config.indicator("field_crowding")),
        "market_pull": _market_pull(results, config.indicator("market_pull")),
        "eu_alignment": _eu_alignment(results),
    }
    indicators = list(ind.values())
    agreements = [i.name for i in indicators if i.favourable]
    conflicts = _detect_conflicts(ind)

    routing, rationale = _route(agreements, conflicts)
    return Corroboration(
        routing=routing,
        rationale=rationale,
        indicators=indicators,
        agreements=agreements,
        conflicts=conflicts,
    )


def _detect_conflicts(ind: dict[str, Indicator]) -> list[str]:
    conflicts: list[str] = []
    # The spec's licensing/parking pattern: capital/regulatory pull into a crowded
    # field, yet industry has not cited THIS asset.
    if (
        ind["market_pull"].level in ("weak", "strong")
        and ind["field_crowding"].level == "crowded"
        and ind["industry_attention"].level == "none"
    ):
        conflicts.append(
            "market/regulatory pull into a crowded field, but no forward citations "
            "of this asset — interest exists yet industry has not picked up THIS asset"
        )
    return conflicts


def _route(agreements: list[str], conflicts: list[str]) -> tuple[Routing, str]:
    if conflicts:
        return (
            Routing.LICENCE_OR_PARK,
            "conflicting signals: pull without validation — licence or park, do not sprint",
        )
    if len(agreements) >= 3:
        return (
            Routing.SPRINT,
            f"{len(agreements)} streams corroborate ({', '.join(agreements)}) — sprint candidate",
        )
    if agreements:
        return (
            Routing.WATCH,
            f"only {', '.join(agreements)} favourable — watch for corroboration",
        )
    return (Routing.PARK, "no favourable signals across streams — park")
