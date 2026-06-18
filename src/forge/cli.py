"""FORGE command-line interface.

Thin wrappers over the existing services so the engine is runnable against a real
database. The DB URL comes from FORGE_DATABASE_URL; credentials (LLM / OPS /
Dealroom) come from the environment — never flags.

    forge db upgrade
    forge assets
    forge ingest-epo EP1000000 EP1000001
    forge dormancy --all
    forge pipeline --all
    forge cluster
    forge dashboard
    forge decide <asset-id> sprint --by committee@org
    forge outcome <asset-id> licensed --by ops@org
    forge recalibrate --since-days 90
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import load_governance_config
from .db.base import create_db_engine, get_database_url, make_session_factory
from .db.models import Asset, DecisionType, OutcomeType
from .governance import GovernanceError, Principal, authorize

# Each command requires a permission; RBAC is enforced before the command runs.
COMMAND_PERMISSIONS = {
    "db": "migrate",
    "assets": "view",
    "ingest-epo": "ingest",
    "dormancy": "view",
    "pipeline": "run_pipeline",
    "cluster": "view",
    "dashboard": "view",
    "decide": "decide",
    "outcome": "record_outcome",
    "recalibrate": "recalibrate",
    "seed": "ingest",
    "serve": "view",
}


def _asset_ids(session: Session, args) -> list[uuid.UUID]:
    if getattr(args, "all", False):
        return list(session.execute(select(Asset.id)).scalars())
    return [uuid.UUID(a) for a in args.asset_ids]


# -- commands (each takes the parsed args + an open session) -----------------
def cmd_db(args, session: Session) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    if args.action == "upgrade":
        command.upgrade(cfg, "head")
    else:
        command.current(cfg)
    return 0


def cmd_assets(args, session: Session) -> int:
    rows = session.execute(select(Asset).order_by(Asset.created_at)).scalars().all()
    if not rows:
        print("(no assets)")
        return 0
    for a in rows:
        print(f"{a.id}  {a.asset_type.value:<14} {a.title or '(untitled)'}")
    return 0


def cmd_ingest_epo(args, session: Session) -> int:
    from .config import load_connectors_config
    from .connectors.epo_ops import EpoOpsConnector, OpsClient, OpsSettings

    settings = OpsSettings.from_config(load_connectors_config("config/connectors.yaml"))
    # The governance policy guards what may be stored (GDPR / rule 4).
    report = EpoOpsConnector(OpsClient(settings)).run(args.refs, session, policy=args.gov)
    print(f"EPO OPS ingest: {report.summary()}")
    for f in report.failed:
        print(f"  FAILED {f.ref} [{f.stage}]: {f.error}")
    return 0 if report.ok else 1


def cmd_dormancy(args, session: Session) -> int:
    from .config import load_dormancy_config, load_organisation_config
    from .dormancy import assess_asset
    from .repository import get_asset

    dcfg = load_dormancy_config("config/dormancy.yaml")
    org = load_organisation_config("config/organisation.yaml")
    for asset_id in _asset_ids(session, args):
        asset = get_asset(session, asset_id)
        if asset is None:
            print(f"{asset_id}: not found")
            continue
        try:
            print(f"{asset.title or asset_id}: {assess_asset(asset, dcfg, org=org).verdict()}")
        except ValueError as exc:
            print(f"{asset.title or asset_id}: n/a ({exc})")
    return 0


def cmd_pipeline(args, session: Session) -> int:
    from .config import load_connectors_config, load_llm_config
    from .llm import build_provider
    from .pipeline import Pipeline, PipelineConfig

    from .governance import assert_residency

    config = PipelineConfig.from_files()
    llm_config = load_llm_config("config/llm.yaml")
    # EU-hosting policy: raise in production_eu if non-EU; advisory warning in dev.
    ok, reason = assert_residency(llm_config.base_url, args.gov)
    if not ok:
        print(f"warning: {reason}", file=sys.stderr)
    provider = build_provider(llm_config)

    s2_client = s1_client = None
    if os.environ.get("FORGE_EPO_OPS_KEY"):
        from .connectors.epo_ops import OpsClient, OpsSettings
        from .streams.s2_patents import OpsS2Client

        ops = OpsClient(OpsSettings.from_config(load_connectors_config("config/connectors.yaml")))
        s2_client = OpsS2Client(ops)
    if os.environ.get("FORGE_DEALROOM_API_KEY"):
        from .connectors.http import UrllibTransport
        from .streams.s1_funding import DealroomS1Client

        s1_client = DealroomS1Client(
            UrllibTransport(), base_url=config.streams.section("s1_funding")["base_url"]
        )

    pipe = Pipeline(config, provider, s2_client=s2_client, s1_client=s1_client)
    report = pipe.run(session, _asset_ids(session, args))
    print(f"pipeline: {report.summary()}")
    for r in report.results:
        routing = r.corroboration.routing.value if r.corroboration else "-"
        score = f"{r.score.value:.2f}" if (r.score and r.score.value is not None) else "  - "
        print(f"  {score}  {routing:<14} {r.asset_id}")
        for err in r.errors:
            print(f"      ! {err}")
    return 0 if report.ok else 1


def cmd_cluster(args, session: Session) -> int:
    from .clustering import ClusterInput, cluster_assets
    from .config import load_sectors_config
    from .repository import get_profile, get_score, latest_decision

    inputs: list[ClusterInput] = []
    for asset in session.execute(select(Asset)).scalars():
        profile = get_profile(session, asset.id)
        if profile is None:
            continue  # only profiled assets cluster
        text = " ".join(
            [profile.problem, profile.solution]
            + list(profile.applications or [])
            + list(profile.query_terms or [])
        )
        # Prefer the live persisted engine score; fall back to the decision snapshot.
        score = get_score(session, asset.id)
        if score is not None:
            ventureability = score.ventureability
        else:
            decision = latest_decision(session, asset.id)
            ventureability = decision.engine_score if decision else None
        inputs.append(
            ClusterInput(
                asset_id=asset.id, title=asset.title, text=text,
                ventureability=ventureability,
            )
        )

    result = cluster_assets(inputs, load_sectors_config("config/sectors.yaml"))
    if not result.clusters:
        print("(no profiled assets to cluster)")
        return 0
    for cluster in result.clusters:
        mean = f"{cluster.mean_score:.2f}" if cluster.mean_score is not None else "n/a"
        print(f"## {cluster.label}  ({cluster.size} assets, mean {mean})")
        for m in cluster.members:
            score = f"{m.ventureability:.2f}" if m.ventureability is not None else "  - "
            print(f"   {score}  {m.title or m.asset_id}")
    return 0


def cmd_dashboard(args, session: Session) -> int:
    from .output.decisions import dashboard

    rows = dashboard(session)
    if not rows:
        print("(no assets)")
        return 0
    print(f"{'score':>6}  {'routing':<14} {'decision':<8} {'outcome':<12} title")
    for r in rows:
        score = f"{r.engine_score:.2f}" if r.engine_score is not None else "  -  "
        print(
            f"{score:>6}  {r.engine_routing or '-':<14} {r.decision or 'pending':<8} "
            f"{r.outcome or '-':<12} {(r.title or '')[:40]}"
        )
    return 0


def cmd_decide(args, session: Session) -> int:
    from .output.decisions import capture_decision
    from .repository import get_asset

    asset = get_asset(session, uuid.UUID(args.asset_id))
    if asset is None:
        print(f"{args.asset_id}: not found", file=sys.stderr)
        return 1
    capture_decision(
        session, asset, decision=DecisionType[args.decision],
        decided_by=args.by, rationale=args.rationale,
    )
    print(f"recorded decision {args.decision} for {asset.title or asset.id}")
    return 0


def cmd_outcome(args, session: Session) -> int:
    from .output.decisions import capture_outcome
    from .repository import get_asset

    asset = get_asset(session, uuid.UUID(args.asset_id))
    if asset is None:
        print(f"{args.asset_id}: not found", file=sys.stderr)
        return 1
    capture_outcome(session, asset, outcome=OutcomeType[args.outcome],
                    recorded_by=args.by, notes=args.notes)
    print(f"recorded outcome {args.outcome} for {asset.title or asset.id}")
    return 0


def cmd_seed(args, session: Session) -> int:
    from .seed import seed_demo

    report = seed_demo(session, policy=args.gov)
    print(report.summary())
    for err in report.errors:
        print(f"  ! {err}")
    return 0 if not report.errors else 1


def cmd_serve(args, session) -> int:
    import uvicorn

    from .web import create_app

    app = create_app()
    print(f"FORGE demo UI on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_recalibrate(args, session: Session) -> int:
    from .config import load_recalibration_config, load_scoring_config
    from .recalibration import run_recalibration

    since = None
    if args.since_days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    result = run_recalibration(
        session,
        scoring_config=load_scoring_config("config/scoring.yaml"),
        config=load_recalibration_config("config/recalibration.yaml"),
        since=since,
    )
    print(result.summary())
    return 0


# -- parser -----------------------------------------------------------------
def _ids(p: argparse.ArgumentParser) -> None:
    p.add_argument("asset_ids", nargs="*", help="asset ids (or use --all)")
    p.add_argument("--all", action="store_true", help="all assets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge", description="FORGE Mining Engine CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("db", help="database migrations")
    p.add_argument("action", choices=["upgrade", "current"])
    p.set_defaults(func=cmd_db, needs_db=False)

    sub.add_parser("assets", help="list assets").set_defaults(func=cmd_assets)

    p = sub.add_parser("ingest-epo", help="ingest patents from EPO OPS")
    p.add_argument("refs", nargs="+")
    p.set_defaults(func=cmd_ingest_epo)

    p = sub.add_parser("dormancy", help="assess dormancy")
    _ids(p)
    p.set_defaults(func=cmd_dormancy)

    p = sub.add_parser("pipeline", help="run the end-to-end pipeline")
    _ids(p)
    p.set_defaults(func=cmd_pipeline)

    sub.add_parser("cluster", help="cluster profiled assets by sector").set_defaults(func=cmd_cluster)
    sub.add_parser("dashboard", help="print the ranked committee dashboard").set_defaults(func=cmd_dashboard)
    sub.add_parser("seed", help="load synthetic demo assets and score them offline").set_defaults(func=cmd_seed)

    p = sub.add_parser("serve", help="run the demo web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve, needs_db=False)

    p = sub.add_parser("decide", help="record a committee decision")
    p.add_argument("asset_id")
    p.add_argument("decision", choices=[d.name for d in DecisionType])
    p.add_argument("--by", default="committee")
    p.add_argument("--rationale", default=None)
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("outcome", help="record a realised outcome")
    p.add_argument("asset_id")
    p.add_argument("outcome", choices=[o.name for o in OutcomeType])
    p.add_argument("--by", default="ops")
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_outcome)

    p = sub.add_parser("recalibrate", help="run the recalibration loop")
    p.add_argument("--since-days", type=int, default=None)
    p.set_defaults(func=cmd_recalibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    # Governance: load the policy and authorize (RBAC) before touching anything.
    try:
        gov = load_governance_config(
            os.environ.get("FORGE_GOVERNANCE_CONFIG", "config/governance.yaml")
        )
        principal = Principal(
            name=os.environ.get("FORGE_USER", "cli"),
            role=os.environ.get("FORGE_ROLE", "admin"),
        )
        authorize(principal, COMMAND_PERMISSIONS.get(args.command, "admin"), gov)
    except GovernanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # config load problems
        print(f"error: governance config: {exc}", file=sys.stderr)
        return 1
    args.gov = gov

    # Commands that own their own DB lifecycle (or need none) skip the shared
    # session — e.g. `serve` launches a server with a per-request session factory.
    if not getattr(args, "needs_db", True):
        return args.func(args, None)

    try:
        session = make_session_factory(create_db_engine(get_database_url()))()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        return args.func(args, session)
    except (GovernanceError, RuntimeError, ValueError) as exc:  # friendly errors
        session.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
