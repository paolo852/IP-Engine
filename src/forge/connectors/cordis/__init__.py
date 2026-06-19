"""CORDIS connector (E10) — ingest EU project results / KER as dormant assets.

Fetches Key Exploitable Results / project-result records from CORDIS (EU public
open data, CC BY) and normalises them into the L2 ``project_result`` asset schema
with provenance. No credentials: the data is public.
"""

from .client import CordisClient, CordisError, CordisNotFound, CordisSettings
from .connector import CordisConnector
from .parser import ParsedResult, parse_results

__all__ = [
    "CordisConnector",
    "CordisClient",
    "CordisSettings",
    "CordisError",
    "CordisNotFound",
    "ParsedResult",
    "parse_results",
]
