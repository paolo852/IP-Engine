"""EPO Open Patent Services connector (stream S2 — free, built first).

Fetches bibliographic data from OPS and normalises it into the L2 asset schema
with provenance. OAuth2 credentials come from the environment, never source.
"""

from .client import (
    OpsAuthError,
    OpsClient,
    OpsError,
    OpsNotFound,
    OpsSettings,
    OpsThrottled,
)
from .connector import EpoOpsConnector
from .parser import ParsedPatent, parse_biblio

__all__ = [
    "EpoOpsConnector",
    "OpsClient",
    "OpsSettings",
    "OpsError",
    "OpsAuthError",
    "OpsNotFound",
    "OpsThrottled",
    "ParsedPatent",
    "parse_biblio",
]
