"""Capture committee decisions and render the dashboard — the slice-9 demo.

    python scripts/dashboard_demo.py

Self-contained: boots a throwaway PostgreSQL, migrates it, saves a few synthetic
assets, records decisions/outcomes, and prints the ranked pipeline view.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from _pg import start_embedded  # noqa: E402
from forge.db.base import create_db_engine, make_session_factory  # noqa: E402
from forge.db.models import DecisionType, OutcomeType  # noqa: E402
from forge.output.decisions import capture_decision, capture_outcome, dashboard  # noqa: E402
from forge.repository import save_asset  # noqa: E402
from synthetic.assets import minimal_grounded_bundle, synthetic_patent_bundle  # noqa: E402


class _Score:
    def __init__(self, value, coverage):
        self.value, self.coverage = value, coverage


class _Corro:
    def __init__(self, routing):
        self.routing = type("R", (), {"value": routing})


def main() -> int:
    pg = start_embedded()
    os.environ["FORGE_DATABASE_URL"] = pg.url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        session = make_session_factory(create_db_engine(pg.url))()

        hi = save_asset(session, synthetic_patent_bundle())
        lo = save_asset(session, minimal_grounded_bundle())
        save_asset(session, minimal_grounded_bundle())  # unreviewed

        capture_decision(session, hi, decision=DecisionType.sprint, decided_by="committee",
                         score=_Score(0.85, 0.75), corroboration=_Corro("sprint"),
                         rationale="strong corroboration across S2/S3/S4")
        capture_outcome(session, hi, outcome=OutcomeType.in_progress, recorded_by="ops")
        capture_decision(session, lo, decision=DecisionType.park, decided_by="committee",
                         score=_Score(0.30, 0.75), corroboration=_Corro("park"))

        print(f"{'score':>6}  {'routing':<8} {'decision':<8} {'outcome':<12} title")
        print("-" * 70)
        for r in dashboard(session):
            score = f"{r.engine_score:.2f}" if r.engine_score is not None else "  -  "
            print(
                f"{score:>6}  {r.engine_routing or '-':<8} {r.decision or 'pending':<8} "
                f"{r.outcome or '-':<12} {(r.title or '')[:40]}"
            )
        session.close()
        return 0
    finally:
        pg.stop()


if __name__ == "__main__":
    raise SystemExit(main())
