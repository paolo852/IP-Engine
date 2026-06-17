"""S4 — EU taxonomy alignment (deterministic classification; free).

Answers: "does this asset align with EU priorities?" — green (Green Deal),
digital, and critical/strategic technologies. This is a *deterministic* classifier
(no ML, no LLM): the profile text is matched, with word boundaries, against the
configured term sets. Each aligned category becomes a SubSignal and a normalised
EvidenceRecord listing exactly which terms matched, so the verdict is auditable.
"""

from __future__ import annotations

import re

from ..config import TaxonomyConfig
from ..db.models import Licence
from ..enrichment.profiling import AssetProfile
from .analysis import clamp_unit
from .base import EvidenceRecord, SourceSpec, StreamResult, SubSignal

STREAM = "S4_taxonomy"
SOURCE_TYPE = "eu_taxonomy"


def _term_pattern(term: str) -> re.Pattern[str]:
    # Boundaries that treat digits as word chars so "5g" / "6g" match exactly and
    # "ai" never matches inside "rain". Whitespace in multi-word terms is flexible.
    body = r"\s+".join(re.escape(part) for part in term.lower().split())
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


class S4TaxonomyStream:
    """Classify a profile against the configured EU-priority taxonomy."""

    def __init__(self, config: TaxonomyConfig) -> None:
        self.strong_match_count = config.strong_match_count
        # Precompile term patterns per category.
        self._categories = {
            name: {
                "label": spec["label"],
                "terms": [(t, _term_pattern(t)) for t in spec["terms"]],
            }
            for name, spec in config.categories.items()
        }

    def _profile_text(self, profile: AssetProfile) -> str:
        parts = [profile.problem.value, profile.solution.value]
        parts += [a.value for a in profile.applications]
        parts += list(profile.query_terms)
        return " ".join(parts).lower()

    def _matched_terms(self, text: str, terms) -> list[str]:
        seen: list[str] = []
        for term, pattern in terms:
            if pattern.search(text) and term not in seen:
                seen.append(term)
        return seen

    def run(self, profile: AssetProfile) -> StreamResult:
        text = self._profile_text(profile)
        result = StreamResult(stream=STREAM)

        for name, spec in self._categories.items():
            matched = self._matched_terms(text, spec["terms"])
            if not matched:
                continue
            strength = clamp_unit(len(matched) / self.strong_match_count)
            detail = (
                f"{spec['label']} — matched {len(matched)} term(s): "
                + ", ".join(matched)
            )
            evidence = EvidenceRecord(
                stream=STREAM,
                match_strength=strength,
                snippet=f"Aligns with {spec['label']}: {', '.join(matched)}",
                source=SourceSpec(SOURCE_TYPE, Licence.public, f"eu_taxonomy:{name}"),
            )
            result.sub_signals.append(
                SubSignal(
                    name=f"eu_taxonomy:{name}",
                    value=float(len(matched)),
                    detail=detail,
                    evidence=[evidence],
                )
            )

        return result
