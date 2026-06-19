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

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import (
    load_dormancy_config,
    load_governance_config,
    load_organisation_config,
    load_scoring_config,
)
from ..db.base import create_db_engine, get_database_url, make_session_factory
from ..db.models import Asset, AssetType, DecisionType, Licence, OutcomeType, Source
from ..documents import DocumentError, parse_document
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
    delete_asset,
    get_asset,
    get_evidence,
    get_profile,
    get_score,
    get_synthesis,
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
    min_coverage = load_scoring_config(f"{config_dir}/scoring.yaml").min_coverage

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
                "min_coverage": min_coverage,
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

        from urllib.parse import quote

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
        except (DataProtectionError, GroundingError, GovernanceError, ValueError) as exc:
            session.rollback()
            session.close()
            return RedirectResponse(url=f"/new?error={quote(str(exc))}", status_code=303)
        except Exception as exc:  # noqa: BLE001 - surface, don't 500 into a blank page
            session.rollback()
            session.close()
            return RedirectResponse(url=f"/new?error={quote(f'unexpected: {exc}')}", status_code=303)

        score_note = ""
        try:
            _score_asset(session, [asset_id], config_dir)
        except Exception as exc:  # noqa: BLE001 - scoring is best-effort
            session.rollback()
            score_note = f"?note={quote(f'Saved, but scoring incomplete: {exc}')}"
        finally:
            session.close()
        return RedirectResponse(url=f"/asset/{asset_id}{score_note}", status_code=303)

    @app.get("/upload", response_class=HTMLResponse)
    def upload_form(request: Request, error: str | None = None) -> HTMLResponse:
        principal = _principal()
        if not _can(principal, "ingest"):
            raise HTTPException(status_code=403, detail="role may not add assets")
        return _TEMPLATES.TemplateResponse(
            request,
            "upload.html",
            {
                "principal": principal,
                "mode": gov.mode,
                "error": error,
                "licences": [Licence.public, Licence.free, Licence.synthetic],
            },
        )

    @app.post("/upload")
    async def upload_document(
        file: UploadFile = File(...),
        licence: str = Form("public"),
    ):
        principal = _principal()
        try:
            authorize(principal, "ingest", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        from urllib.parse import quote

        raw = await file.read()
        try:
            parsed = parse_document(file.filename or "document", raw)
        except DocumentError as exc:
            return RedirectResponse(url=f"/upload?error={quote(str(exc))}", status_code=303)

        session = session_factory()
        score_note = ""
        try:
            bundle = _bundle_from_parsed(parsed, file.filename or "document", licence)
            asset = save_asset(session, bundle, policy=gov)
            asset_id = asset.id
        except (DataProtectionError, GroundingError, GovernanceError, ValueError) as exc:
            session.rollback()
            session.close()
            return RedirectResponse(url=f"/upload?error={quote(str(exc))}", status_code=303)
        except Exception as exc:  # noqa: BLE001 - surface, don't 500 into a blank page
            session.rollback()
            session.close()
            return RedirectResponse(url=f"/upload?error={quote(f'unexpected: {exc}')}", status_code=303)

        # The asset is stored; scoring is best-effort so an LLM/source hiccup never
        # discards it — land on the asset page with a note if scoring was partial.
        try:
            _score_asset(session, [asset_id], config_dir)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            score_note = f" Scoring incomplete: {exc}."
        finally:
            session.close()

        note = quote(
            f"Classified as {parsed.classification.label} — "
            f"{', '.join(parsed.classification.reasons[:3])}. "
            "Fields were auto-extracted; review them below." + score_note
        )
        return RedirectResponse(url=f"/asset/{asset_id}?note={note}", status_code=303)

    @app.get("/ingest-epo", response_class=HTMLResponse)
    def ingest_epo_form(request: Request, error: str | None = None) -> HTMLResponse:
        principal = _principal()
        if not _can(principal, "ingest"):
            raise HTTPException(status_code=403, detail="role may not add assets")
        return _TEMPLATES.TemplateResponse(
            request,
            "ingest_epo.html",
            {
                "principal": principal,
                "mode": gov.mode,
                "error": error,
                "has_key": bool(os.environ.get("FORGE_EPO_OPS_KEY")),
            },
        )

    @app.post("/ingest-epo")
    def ingest_epo(refs: str = Form(...)):
        principal = _principal()
        try:
            authorize(principal, "ingest", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        from urllib.parse import quote

        ref_list = [r for r in refs.replace(",", " ").split() if r]
        if not ref_list:
            return RedirectResponse(
                url="/ingest-epo?error=" + quote("enter a patent number (e.g. EP1000000)"),
                status_code=303,
            )
        if not os.environ.get("FORGE_EPO_OPS_KEY"):
            return RedirectResponse(
                url="/ingest-epo?error="
                + quote("EPO OPS not configured: set FORGE_EPO_OPS_KEY and FORGE_EPO_OPS_SECRET"),
                status_code=303,
            )

        session = session_factory()
        try:
            from ..config import load_connectors_config
            from ..connectors.epo_ops import EpoOpsConnector, OpsClient, OpsSettings

            settings = OpsSettings.from_config(
                load_connectors_config(f"{config_dir}/connectors.yaml")
            )
            report = EpoOpsConnector(OpsClient(settings)).run(
                ref_list, session, policy=gov
            )
        except Exception as exc:  # noqa: BLE001 - surface EPO/network errors
            session.rollback()
            session.close()
            return RedirectResponse(
                url="/ingest-epo?error=" + quote(f"EPO error: {exc}"), status_code=303
            )

        if not report.saved:
            session.close()
            if report.failed:
                f = report.failed[0]
                msg = f"{f.ref} [{f.stage}]: {f.error}"
            else:
                msg = "nothing new — those patents are already ingested"
            return RedirectResponse(url="/ingest-epo?error=" + quote(msg), status_code=303)

        # Clean biblio is stored; score it (S2 citations included since the EPO key
        # is set). Best-effort scoring — the asset is kept either way.
        asset_id = report.saved[0]
        score_note = ""
        try:
            _score_asset(session, list(report.saved), config_dir)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            score_note = f" Scoring incomplete: {exc}."
        finally:
            session.close()
        note = quote(
            f"Ingested {len(report.saved)} patent(s) from EPO OPS "
            f"(clean biblio: title, abstract, dates)." + score_note
        )
        return RedirectResponse(url=f"/asset/{asset_id}?note={note}", status_code=303)

    @app.get("/asset/{asset_id}", response_class=HTMLResponse)
    def asset_detail(request: Request, asset_id: str, note: str | None = None) -> HTMLResponse:
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

            score = get_score(session, aid)
            # Coverage-as-signal: an evidence-poor score (too many indeterminate
            # dimensions — usually no MARKET signal found) is provisional, not a
            # reliable number, and is surfaced as "needs human review".
            low_evidence = score is None or score.ventureability is None or (
                score.coverage < min_coverage
            )
            profile = get_profile(session, aid)
            ctx = {
                "asset": asset,
                "provenance": list(asset.provenance),
                "dormancy": dormancy,
                "profile": profile,
                "synthesis": get_synthesis(session, aid),
                "score": score,
                "low_evidence": low_evidence,
                "review_reason": _review_reason(profile, low_evidence),
                "min_coverage": min_coverage,
                "evidence": get_evidence(session, aid),
                "decision": latest_decision(session, aid),
                "outcome": latest_outcome(session, aid),
                "decision_types": list(DecisionType),
                "outcome_types": list(OutcomeType),
                "principal": principal,
                "can_decide": _can(principal, "decide"),
                "can_record_outcome": _can(principal, "record_outcome"),
                "can_delete": _can(principal, "delete_asset"),
                "note": note,
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

    @app.post("/asset/{asset_id}/delete")
    def delete(asset_id: str) -> RedirectResponse:
        principal = _principal()
        try:
            authorize(principal, "delete_asset", gov)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        try:
            aid = uuid.UUID(asset_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="invalid asset id")

        session = session_factory()
        try:
            removed = delete_asset(session, aid)
        finally:
            session.close()
        if not removed:
            raise HTTPException(status_code=404, detail="asset not found")
        return RedirectResponse(url="/", status_code=303)

    return app


def _review_reason(profile, low_evidence: bool) -> str | None:
    """Why an evidence-poor asset is flagged — the same distinction the pipeline's
    E2 re-query draws, derived here at read time: did the profiler produce market
    queries at all, or did genuine market terms still find little signal?

    The engine only routes to human review with a reason; it never decides (rule 7).
    """
    if not low_evidence:
        return None
    apps = (getattr(profile, "candidate_applications", None) or []) if profile else []
    has_market_terms = any((a or {}).get("industry_terms") for a in apps)
    if has_market_terms:
        return (
            "Market terms were generated and searched, but the streams still found "
            "little signal — this looks like a genuinely weak market rather than a "
            "query problem. An analyst should confirm before discarding."
        )
    return (
        "The profiler produced no market/application search terms (only the asset's "
        "technical vocabulary), so the streams searched the wrong thing. Sharpen the "
        "candidate markets and re-run before trusting any ranking."
    )


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


def _bundle_from_parsed(parsed, filename: str, licence: str) -> AssetBundle:
    """Build a grounded AssetBundle from an auto-parsed uploaded document.

    The document is the source: the asset_type comes from the (explainable)
    classification, the extracted fields are grounded to the file, and governance
    decides storability for the chosen licence.
    """
    asset = Asset(
        asset_type=parsed.asset_type,
        source_layer="L1.upload",
        title=parsed.fields.get("title"),
        abstract=parsed.fields.get("abstract"),
        claims_or_description=parsed.fields.get("claims_or_description"),
    )
    source = Source(source_type="upload", licence=Licence(licence), locator=filename)
    provenance = [
        ProvenanceEntry(field_name=name, source=source, note="auto-extracted from upload")
        for name in asset.populated_groundable_fields()
    ]
    return AssetBundle(asset=asset, provenance=provenance)


def _profiling_provider(config_dir: str):
    """Use the real LLM when a key is configured, else the offline placeholder.

    The hosted LLM is what turns claims/technology statements into reframed
    problem/solution/application scenarios (still quote-grounded). Without a key,
    the offline provider only copies verbatim spans — honest, but not reframed.
    """
    from ..llm.provider import API_KEY_ENV
    from ..seed import OfflineProfilingProvider

    if os.environ.get(API_KEY_ENV) or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from ..config import load_llm_config
            from ..llm.provider import build_provider

            return build_provider(load_llm_config(f"{config_dir}/llm.yaml"))
        except Exception:  # noqa: BLE001 - fall back rather than fail the add
            return OfflineProfilingProvider()
    return OfflineProfilingProvider()


def _score_asset(session, asset_ids, config_dir: str) -> None:
    """Profile, cross-reference and score freshly-added assets.

    Runs S3/S4 always; S2 (free EPO OPS) and S1 (licensed Dealroom) activate when
    their credentials are configured, enriching the score with real patent and
    funding signals.
    """
    from ..pipeline import Pipeline, PipelineConfig
    from ..seed import build_stream_clients

    config = PipelineConfig.from_files(config_dir=config_dir)
    s2_client, s1_client = build_stream_clients(config_dir)
    Pipeline(
        config,
        _profiling_provider(config_dir),
        s2_client=s2_client,
        s1_client=s1_client,
    ).run(session, asset_ids)
