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
from ..db.models import Asset, AssetType, DecisionType, Licence, OutcomeType, Source
from ..dormancy import assess_asset
from ..governance import (
    AuthorizationError,
    DataProtectionError,
    GovernanceError,
    Principal,
    authorize,
    permissions_for,
)
from ..output.decisions import capture_decision, capture_outcome, dashboard
from ..repository import (
    AssetBundle,
    GroundingError,
    ProvenanceEntry,
    get_asset,
    get_evidence,
    get_profile,
    get_score,
    latest_decision,
    latest_outcome,
    save_asset,
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
            {
                "rows": rows,
                "principal": principal,
                "mode": gov.mode,
                "can_ingest": _can(principal, "ingest"),
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    def new_asset_form(request: Request, error: str | None = None) -> HTMLResponse:
        principal = _principal()
        if not _can(principal, "ingest"):
            raise HTTPException(status_code=403, detail="role may not add assets")
        return _TEMPLATES.TemplateResponse(
            request,
            "new.html",
            {
                "principal": principal,
                "mode": gov.mode,
                "error": error,
                "asset_types": [t for t in AssetType if t.value not in gov.restricted_asset_types],
                "licences": [Licence.public, Licence.free, Licence.synthetic],
            },
        )

    @app.post("/new")
    def create_asset(
        title: str = Form(...),
        source_locator: str = Form(...),
        licence: str = Form("public"),
        asset_type: str = Form("patent"),
        abstract: str = Form(""),
        claims_or_description: str = Form(""),
        legal_status: str = Form(""),
        fee_status: str = Form(""),
        priority_date: str = Form(""),
        filing_date: str = Form(""),
        grant_date: str = Form(""),
        inventors: str = Form(""),
        owners: str = Form(""),
    ):
        principal = _principal()
        try:
            authorize(principal, "ingest", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        session = session_factory()
        try:
            bundle = _bundle_from_form(
                title=title, source_locator=source_locator, licence=licence,
                asset_type=asset_type, abstract=abstract,
                claims_or_description=claims_or_description, legal_status=legal_status,
                fee_status=fee_status, priority_date=priority_date,
                filing_date=filing_date, grant_date=grant_date,
                inventors=inventors, owners=owners,
            )
            asset = save_asset(session, bundle, policy=gov)
            asset_id = asset.id
            _score_offline(session, [asset_id], config_dir)
        except (DataProtectionError, GroundingError, GovernanceError, ValueError) as exc:
            session.rollback()
            # Bounce back to the form with a readable message (governance/grounding).
            from urllib.parse import quote

            return RedirectResponse(url=f"/new?error={quote(str(exc))}", status_code=303)
        finally:
            session.close()
        return RedirectResponse(url=f"/asset/{asset_id}", status_code=303)

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


def _csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _bundle_from_form(
    *,
    title: str,
    source_locator: str,
    licence: str,
    asset_type: str,
    abstract: str,
    claims_or_description: str,
    legal_status: str,
    fee_status: str,
    priority_date: str,
    filing_date: str,
    grant_date: str,
    inventors: str,
    owners: str,
) -> AssetBundle:
    """Build a grounded AssetBundle from the add-asset form.

    Every populated factual field is grounded to the single user-supplied source
    (a URL / reference), so the grounding rule holds; governance then decides
    whether the (asset_type, licence) is storable in the current mode.
    """
    if not title.strip():
        raise ValueError("title is required")
    if not source_locator.strip():
        raise ValueError("a source (URL or reference) is required to ground the asset")

    key_dates = {
        k: v
        for k, v in (
            ("priority_date", priority_date.strip()),
            ("filing_date", filing_date.strip()),
            ("grant_date", grant_date.strip()),
        )
        if v
    }
    asset = Asset(
        asset_type=AssetType(asset_type),
        source_layer="L1.manual",
        title=title.strip(),
        abstract=abstract.strip() or None,
        claims_or_description=claims_or_description.strip() or None,
        legal_status=legal_status.strip() or None,
        fee_status=fee_status.strip() or None,
        key_dates=key_dates or None,
        inventors=_csv(inventors) or None,
        owners=_csv(owners) or None,
    )
    source = Source(
        source_type="manual",
        licence=Licence(licence),
        locator=source_locator.strip(),
    )
    provenance = [
        ProvenanceEntry(field_name=name, source=source, note="user-entered")
        for name in asset.populated_groundable_fields()
    ]
    return AssetBundle(asset=asset, provenance=provenance)


def _score_offline(session, asset_ids, config_dir: str) -> None:
    """Score freshly-added assets with the offline pipeline (no LLM key needed)."""
    from ..pipeline import Pipeline, PipelineConfig
    from ..seed import OfflineProfilingProvider

    config = PipelineConfig.from_files(config_dir=config_dir)
    Pipeline(config, OfflineProfilingProvider()).run(session, asset_ids)
