"""L5 output — committee-facing artifacts.

The market-context brief is the first: a grounded document with ZERO unsourced
factual sentences. It is composed deterministically from already-grounded inputs
(profile, dormancy, stream evidence, corroboration, score), so the grounding rule
holds by construction and is verified before the brief is returned.
"""

from .brief import (
    BriefError,
    BriefInputs,
    BriefSection,
    MarketContextBrief,
    SourceRef,
    Statement,
    build_brief,
)

__all__ = [
    "BriefError",
    "BriefInputs",
    "BriefSection",
    "MarketContextBrief",
    "SourceRef",
    "Statement",
    "build_brief",
]
