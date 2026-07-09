"""Glue: generate an asset's need hypotheses from its stored profile + the graph."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import NeedsConfig
from ..db.models import Asset, NeedHypothesis
from .need_hypothesis import generate
from .repository import save_need_hypotheses


def run_matching(session: Session, asset: Asset, *, cfg: NeedsConfig) -> list[NeedHypothesis]:
    """Generate and persist need hypotheses for an asset from its stored signals.

    Reads the asset's profile (candidate applications + technology summary), the
    Relationship Graph companies, and whether the asset has corroborating
    cross-stream evidence, then replaces the asset's hypotheses with fresh drafts.
    """
    from ..graph import get_companies
    from ..repository import get_evidence, get_profile

    profile = get_profile(session, asset.id)
    applications = (getattr(profile, "candidate_applications", None) or []) if profile else []
    technology_summary = getattr(profile, "technology_summary", None) if profile else None

    drafts = generate(
        applications=applications,
        technology_summary=technology_summary,
        companies=get_companies(session),
        market_signal=bool(get_evidence(session, asset.id)),
        cfg=cfg,
    )
    return save_need_hypotheses(session, asset, drafts)
