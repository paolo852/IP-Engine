"""FastAPI application factory for the FORGE demo UI.

Reads from the FORGE store via the existing repository/read-model functions and
writes only committee decisions/outcomes (humans decide). RBAC is enforced with
the same governance policy as the CLI: the acting principal comes from
FORGE_USER/FORGE_ROLE, and write routes require the matching permission.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import (
    load_dormancy_config,
    load_governance_config,
    load_organisation_config,
)
from ..db.base import create_db_engine, get_database_url, make_session_factory
from ..db.models import Asset, DecisionType, OutcomeType
from ..dormancy import assess_asset
from ..governance import AuthorizationError, Principal, authorize, permissions_for
from ..output.decisions import capture_decision, capture_outcome, dashboard
from ..repository import (
    get_asset,
    get_evidence,
    get_profile,
    get_score,
    latest_decision,
    latest_outcome,
)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _principal() -> Principal:
    """The acting user, read per-request so the role can change between calls."""
    return Principal(
        name=os.environ.get("FORGE_USER", "demo"),
        role=os.environ.get("FORGE_ROLE", "admin"),
    )


def create_app(
    *,
    session_factory=None,
    governance_path: str | None = None,
    config_dir: str = "config",
) -> FastAPI:
    """Build the demo app. ``session_factory`` is injectable for tests."""
    app = FastAPI(title="FORGE Mining Engine — demo")

    if session_factory is None:
        session_factory = make_session_factory(create_db_engine(get_database_url()))
    gov = load_governance_config(
        governance_path
        or os.environ.get("FORGE_GOVERNANCE_CONFIG", f"{config_dir}/governance.yaml")
    )
    dormancy_cfg = load_dormancy_config(f"{config_dir}/dormancy.yaml")
    org_cfg = load_organisation_config(f"{config_dir}/organisation.yaml")

    app.state.session_factory = session_factory
    app.state.governance = gov

    def _can(principal: Principal, permission: str) -> bool:
        try:
            return permission in permissions_for(principal.role, gov)
        except AuthorizationError:
            return False

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        principal = _principal()
        session = session_factory()
        try:
            rows = dashboard(session)
        finally:
            session.close()
        return _TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"rows": rows, "principal": principal, "mode": gov.mode},
        )

    @app.get("/asset/{asset_id}", response_class=HTMLResponse)
    def asset_detail(request: Request, asset_id: str) -> HTMLResponse:
        principal = _principal()
        try:
            aid = uuid.UUID(asset_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="invalid asset id")

        session = session_factory()
        try:
            asset = get_asset(session, aid)
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")

            try:
                dormancy = assess_asset(asset, dormancy_cfg, org=org_cfg)
            except ValueError:
                dormancy = None  # no ruleset for this asset type

            ctx = {
                "asset": asset,
                "provenance": list(asset.provenance),
                "dormancy": dormancy,
                "profile": get_profile(session, aid),
                "score": get_score(session, aid),
                "evidence": get_evidence(session, aid),
                "decision": latest_decision(session, aid),
                "outcome": latest_outcome(session, aid),
                "decision_types": list(DecisionType),
                "outcome_types": list(OutcomeType),
                "principal": principal,
                "can_decide": _can(principal, "decide"),
                "can_record_outcome": _can(principal, "record_outcome"),
            }
            return _TEMPLATES.TemplateResponse(request, "asset.html", ctx)
        finally:
            session.close()

    @app.post("/asset/{asset_id}/decide")
    def decide(
        asset_id: str,
        decision: str = Form(...),
        decided_by: str = Form("committee"),
        rationale: str = Form(""),
    ) -> RedirectResponse:
        principal = _principal()
        try:
            authorize(principal, "decide", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if decision not in DecisionType.__members__:
            raise HTTPException(status_code=400, detail="unknown decision")

        session = session_factory()
        try:
            asset = get_asset(session, uuid.UUID(asset_id))
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            score = get_score(session, asset.id)
            capture_decision(
                session,
                asset,
                decision=DecisionType[decision],
                decided_by=decided_by or principal.name,
                rationale=rationale or None,
                score=_ScoreSnapshot(score) if score else None,
            )
        finally:
            session.close()
        return RedirectResponse(url=f"/asset/{asset_id}", status_code=303)

    @app.post("/asset/{asset_id}/outcome")
    def outcome(
        asset_id: str,
        outcome: str = Form(...),
        recorded_by: str = Form("ops"),
        notes: str = Form(""),
    ) -> RedirectResponse:
        principal = _principal()
        try:
            authorize(principal, "record_outcome", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if outcome not in OutcomeType.__members__:
            raise HTTPException(status_code=400, detail="unknown outcome")

        session = session_factory()
        try:
            asset = get_asset(session, uuid.UUID(asset_id))
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            capture_outcome(
                session,
                asset,
                outcome=OutcomeType[outcome],
                recorded_by=recorded_by or principal.name,
                notes=notes or None,
            )
        finally:
            session.close()
        return RedirectResponse(url=f"/asset/{asset_id}", status_code=303)

    return app


class _ScoreSnapshot:
    """Adapt a persisted AssetScore to the (value, coverage) shape capture wants."""

    def __init__(self, score) -> None:
        self.value = score.ventureability
        self.coverage = score.coverage
