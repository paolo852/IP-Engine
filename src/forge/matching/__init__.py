"""Need-matching (T11+): falsifiable need hypotheses over the Relationship Graph.

A hypothesis is only ever a hypothesis (rule 4) — it becomes a real need only when
a human validation confirms it. Everything here produces grounded, testable
hypotheses; nothing decides.
"""

from .need_hypothesis import MODEL, NeedHypothesisDraft, generate
from .repository import get_need_hypotheses, save_need_hypotheses
from .service import run_matching

__all__ = [
    "generate",
    "NeedHypothesisDraft",
    "MODEL",
    "save_need_hypotheses",
    "get_need_hypotheses",
    "run_matching",
]
