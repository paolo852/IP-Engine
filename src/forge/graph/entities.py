"""Company entity resolution (T10) — a deterministic normalisation key.

Two records refer to the same company when their names normalise to the same
key: lower-cased, punctuation-flattened, and stripped of legal-form suffixes
(GmbH, Ltd, S.p.A, …) that vary across registries but do not identify the firm.
``registry_id`` (PIC/VAT), when present, is the stronger match and is resolved
first by the repository; this is the fallback when only a name is known.
"""

from __future__ import annotations

import re

# Legal-form tokens dropped when they appear as separate words in a company name.
# Kept intentionally conservative — only unambiguous corporate/legal suffixes.
_LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        "inc", "incorporated", "ltd", "limited", "llc", "llp", "plc", "corp",
        "corporation", "co", "company", "gmbh", "ag", "kg", "kgaa", "sa", "sas",
        "sarl", "spa", "srl", "sl", "slu", "bv", "nv", "oy", "oyj", "ab", "as",
        "asa", "aps", "kk", "kabushiki", "pty", "pte", "sro", "gie", "scarl",
        "the",
    }
)


def normalize_company_name(name: str) -> str:
    """Return the entity-resolution key for a company name.

    Lower-cases, replaces any non-alphanumeric run with a single space, drops
    legal-form suffix tokens, and collapses whitespace. Falls back to the
    suffix-retaining form if stripping would empty the name (e.g. name == "Ltd").
    """
    # Drop periods first (without splitting) so dotted acronym suffixes collapse:
    # "S.p.A." -> "spa", "G.m.b.H." -> "gmbh" -> then recognised and stripped.
    no_dots = (name or "").lower().replace(".", "")
    flattened = re.sub(r"[^a-z0-9]+", " ", no_dots).strip()
    if not flattened:
        return ""
    tokens = flattened.split()
    kept = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(kept) if kept else flattened
