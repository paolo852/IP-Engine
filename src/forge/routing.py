"""Two-axis routing (T14, brief §L4.4) — need × TRL → four outcomes.

Routing is NOT the score. It is the deterministic crossing of two HUMAN
validations the engine prepares but does not decide:

  * the NEED axis — from the company (need_validation): customer / producer / none;
  * the TRL axis — from the inventor (inventor_trl_check): high (~6-9) / low (~2-4).

It stays PENDING until BOTH records exist. Then:

    | need\\TRL  | high            | low                    |
    | customer  | venture (sprint)| needs-oriented matur.  |
    | producer  | licensing       | option / co-development|
    | none      | park (logged)   | park (logged)          |

The suggestion is stored; the committee decides (both are kept). Nothing here
decides an asset's fate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import TrlConfig
from .db.models import (
    Asset,
    AssetRouting,
    NeedAxis,
    RouteType,
    RoutingStatus,
    Track,
    TrlAxis,
)
from .validation import (
    confirmed_tracks,
    has_any_need_validation,
    latest_trl_check,
)

# The four-outcome table. Customer confirmation takes precedence over producer
# when BOTH are confirmed (venture creation is the flagship route).
_ROUTES: dict[tuple[NeedAxis, TrlAxis], RouteType] = {
    (NeedAxis.customer, TrlAxis.high): RouteType.venture,
    (NeedAxis.customer, TrlAxis.low): RouteType.maturation,
    (NeedAxis.producer, TrlAxis.high): RouteType.licensing,
    (NeedAxis.producer, TrlAxis.low): RouteType.option,
    (NeedAxis.none, TrlAxis.high): RouteType.park,
    (NeedAxis.none, TrlAxis.low): RouteType.park,
}


@dataclass
class RoutingResult:
    status: RoutingStatus
    need_axis: NeedAxis | None
    trl_axis: TrlAxis | None
    suggested_route: RouteType | None
    rationale: str


def resolve_need_axis(confirmed: set[Track]) -> NeedAxis:
    """Reduce the confirmed tracks to a single need axis (customer takes priority)."""
    if Track.customer in confirmed:
        return NeedAxis.customer
    if Track.producer in confirmed:
        return NeedAxis.producer
    return NeedAxis.none


def decide_route(need_axis: NeedAxis, trl_axis: TrlAxis) -> RouteType:
    return _ROUTES[(need_axis, trl_axis)]


def compute_routing(session: Session, asset_id: uuid.UUID, *, trl_cfg: TrlConfig) -> RoutingResult:
    """Cross the two axes for an asset. PENDING until both human records exist."""
    trl = latest_trl_check(session, asset_id)
    has_need = has_any_need_validation(session, asset_id)

    if trl is None or not has_need:
        missing = []
        if not has_need:
            missing.append("a company need validation")
        if trl is None:
            missing.append("the inventor's TRL band")
        return RoutingResult(
            status=RoutingStatus.pending,
            need_axis=None,
            trl_axis=None,
            suggested_route=None,
            rationale="Routing pending — awaiting " + " and ".join(missing)
            + ". Routing is the crossing of two human validations, not the score.",
        )

    need_axis = resolve_need_axis(confirmed_tracks(session, asset_id))
    trl_axis = TrlAxis.high if trl_cfg.is_high(trl.trl_band) else TrlAxis.low
    route = decide_route(need_axis, trl_axis)
    rationale = (
        f"Need axis: {need_axis.value}; TRL axis: {trl_axis.value} "
        f"(inventor band {trl.trl_band}). Suggested route: {route.value}. "
        "A suggestion for the committee — humans decide."
    )
    return RoutingResult(
        status=RoutingStatus.ready,
        need_axis=need_axis,
        trl_axis=trl_axis,
        suggested_route=route,
        rationale=rationale,
    )


def save_routing(session: Session, asset: Asset, result: RoutingResult) -> AssetRouting:
    """Persist (upsert) the routing suggestion. One row per asset, recomputed
    in place; a recorded committee_decision is preserved across recomputes."""
    row = session.execute(
        select(AssetRouting).where(AssetRouting.asset_id == asset.id)
    ).scalar_one_or_none()
    if row is None:
        row = AssetRouting(asset=asset)
        session.add(row)
    row.status = result.status
    row.need_axis = result.need_axis
    row.trl_axis = result.trl_axis
    row.suggested_route = result.suggested_route
    row.rationale = result.rationale
    session.commit()
    return row


def get_routing(session: Session, asset_id: uuid.UUID) -> AssetRouting | None:
    return session.execute(
        select(AssetRouting).where(AssetRouting.asset_id == asset_id)
    ).scalar_one_or_none()


def route_asset(session: Session, asset: Asset, *, trl_cfg: TrlConfig) -> AssetRouting:
    """Compute and persist an asset's routing suggestion."""
    return save_routing(session, asset, compute_routing(session, asset.id, trl_cfg=trl_cfg))
