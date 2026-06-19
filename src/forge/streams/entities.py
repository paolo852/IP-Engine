"""Citing-entity classification (E4): corporate vs academic vs other.

A forward citation tells us the field noticed an asset; *who* cited it tells us
whether INDUSTRY noticed it. A citation from a company is a far stronger
adoption/defensibility signal than one from a university or research institute,
which is closer to the asset's own academic lineage. This module buckets an
applicant name into one of three kinds using config-supplied marker lists
(rule 3: CONFIG, not code — extend the lists without touching this file).

The match is deterministic and explainable: names are normalised to lowercase
word tokens and a marker matches only on a word boundary, so ``inc`` matches
"Acme Inc" but not "Increment Labs".
"""

from __future__ import annotations

import re

CORPORATE = "corporate"
ACADEMIC = "academic"
OTHER = "other"

# Conservative, public, language-spanning defaults. Overridable via config.
DEFAULT_ACADEMIC_MARKERS: tuple[str, ...] = (
    "university", "università", "universität", "universite", "universidad",
    "institute", "institut", "college", "école", "ecole", "polytechnic",
    "politecnico", "academy", "accademia", "fraunhofer", "max planck", "cnrs",
    "csic", "research council", "research centre", "research center",
    "national laboratory", "hospital", "klinik", "foundation for research",
)
DEFAULT_CORPORATE_MARKERS: tuple[str, ...] = (
    "inc", "ltd", "limited", "gmbh", "llc", "corp", "corporation", "co", "ag",
    "sa", "spa", "srl", "bv", "oy", "ab", "plc", "kk", "kabushiki", "pty",
    "company", "technologies", "systems", "electronics", "semiconductor",
    "pharmaceuticals", "industries", "holdings",
)


def _normalise(text: str) -> str:
    """Lowercase, reduce to space-separated alnum tokens, space-padded."""
    tokens = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return f" {tokens} "


def _matches(padded: str, marker: str) -> bool:
    m = re.sub(r"[^a-z0-9]+", " ", marker.lower()).strip()
    return bool(m) and f" {m} " in padded


def classify_entity(
    name: str | None,
    *,
    academic_markers: tuple[str, ...] | list[str] = DEFAULT_ACADEMIC_MARKERS,
    corporate_markers: tuple[str, ...] | list[str] = DEFAULT_CORPORATE_MARKERS,
) -> str:
    """Bucket an applicant/citing name into corporate / academic / other.

    Academic is checked first: a research body that also looks corporate (e.g.
    a university-owned company) is treated as academic lineage, the more
    conservative reading for an *industry-adoption* signal.
    """
    if not name or not name.strip():
        return OTHER
    padded = _normalise(name)
    if any(_matches(padded, mk) for mk in academic_markers):
        return ACADEMIC
    if any(_matches(padded, mk) for mk in corporate_markers):
        return CORPORATE
    return OTHER


def markers_from_config(config: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read (academic, corporate) marker lists from an ``entity_classification``
    config section, falling back to the defaults when unset."""
    section = (config or {}).get("entity_classification") or {}
    academic = section.get("academic_markers") or DEFAULT_ACADEMIC_MARKERS
    corporate = section.get("corporate_markers") or DEFAULT_CORPORATE_MARKERS
    return tuple(academic), tuple(corporate)
