"""T14: two-axis routing — the four outcomes, pending gating, precedence."""

from __future__ import annotations

import pytest

from forge.config import load_trl_config
from forge.db.models import NeedAxis, NeedOutcome, RouteType, RoutingStatus, Track, TrlAxis
from forge.graph import resolve_company
from forge.repository import save_asset
from forge.routing import (
    compute_routing,
    decide_route,
    get_routing,
    resolve_need_axis,
    route_asset,
)
from forge.validation import record_need_validation, record_trl_check

from .synthetic.assets import synthetic_patent_bundle

TRL = load_trl_config("config/trl.yaml")


# -- the pure crossing ------------------------------------------------------
@pytest.mark.parametrize(
    "need,trl,expected",
    [
        (NeedAxis.customer, TrlAxis.high, RouteType.venture),
        (NeedAxis.customer, TrlAxis.low, RouteType.maturation),
        (NeedAxis.producer, TrlAxis.high, RouteType.licensing),
        (NeedAxis.producer, TrlAxis.low, RouteType.option),
        (NeedAxis.none, TrlAxis.high, RouteType.park),
        (NeedAxis.none, TrlAxis.low, RouteType.park),
    ],
)
def test_four_outcome_table(need, trl, expected):
    assert decide_route(need, trl) is expected


def test_customer_takes_precedence_over_producer():
    assert resolve_need_axis({Track.customer, Track.producer}) is NeedAxis.customer
    assert resolve_need_axis({Track.producer}) is NeedAxis.producer
    assert resolve_need_axis(set()) is NeedAxis.none


# -- pending gating (needs both records) ------------------------------------
def _asset(session):
    a = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    session.commit()
    return a, company


def test_pending_without_any_validation(session):
    asset, _ = _asset(session)
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.status is RoutingStatus.pending and r.suggested_route is None
    assert "need validation" in r.rationale and "TRL" in r.rationale


def test_pending_with_need_but_no_trl(session):
    asset, company = _asset(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.customer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.status is RoutingStatus.pending
    assert "TRL" in r.rationale and "need validation" not in r.rationale


def test_pending_with_trl_but_no_need(session):
    asset, _ = _asset(session)
    record_trl_check(session, asset, trl_band="6-9", recorded_by="inv")
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.status is RoutingStatus.pending
    assert "need validation" in r.rationale


# -- ready outcomes end to end ----------------------------------------------
def test_customer_confirmed_high_trl_routes_to_venture(session):
    asset, company = _asset(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.customer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    record_trl_check(session, asset, trl_band="6-9", recorded_by="inv")
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.status is RoutingStatus.ready
    assert r.need_axis is NeedAxis.customer and r.trl_axis is TrlAxis.high
    assert r.suggested_route is RouteType.venture


def test_producer_confirmed_low_trl_routes_to_option(session):
    asset, company = _asset(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    record_trl_check(session, asset, trl_band="2-4", recorded_by="inv")
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.suggested_route is RouteType.option and r.trl_axis is TrlAxis.low


def test_denied_need_routes_to_park(session):
    asset, company = _asset(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.customer,
                           outcome=NeedOutcome.need_denied, validated_by="a")
    record_trl_check(session, asset, trl_band="6-9", recorded_by="inv")
    r = compute_routing(session, asset.id, trl_cfg=TRL)
    assert r.need_axis is NeedAxis.none and r.suggested_route is RouteType.park


# -- persistence / recompute ------------------------------------------------
def test_route_asset_persists_and_recomputes_in_place(session):
    asset, company = _asset(session)
    record_trl_check(session, asset, trl_band="2-4", recorded_by="inv")
    route_asset(session, asset, trl_cfg=TRL)  # pending (no need yet)
    assert get_routing(session, asset.id).status is RoutingStatus.pending

    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    route_asset(session, asset, trl_cfg=TRL)  # recompute -> ready, same row
    row = get_routing(session, asset.id)
    assert row.status is RoutingStatus.ready and row.suggested_route is RouteType.option
    # one row per asset (recomputed in place)
    from forge.db.models import AssetRouting
    from sqlalchemy import func, select
    assert session.execute(
        select(func.count()).select_from(AssetRouting).where(AssetRouting.asset_id == asset.id)
    ).scalar_one() == 1
