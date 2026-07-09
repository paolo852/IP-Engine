"""Relationship Graph (T10) — companies, ties, and contacts, populated in layers.

The graph gives a RELATIONSHIP (not a need); it is what later makes need
hypotheses specific and reachable. Company-level data is broadly accessible;
contacts (personal data) are isolated behind stricter governance access.
"""

from .cordis_layer0 import Layer0Report, build_layer0, populate_from_cordis_project
from .entities import normalize_company_name
from .repository import (
    add_relationship,
    find_company,
    get_companies,
    get_relationships_for,
    resolve_company,
)

__all__ = [
    "normalize_company_name",
    "resolve_company",
    "add_relationship",
    "get_companies",
    "find_company",
    "get_relationships_for",
    "build_layer0",
    "populate_from_cordis_project",
    "Layer0Report",
]
