"""Run the quarterly recalibration loop over synthetic history — slice-10 demo.

    python scripts/recalibration_demo.py

Self-contained: boots a throwaway PostgreSQL, migrates it, records decisions +
realised outcomes, runs recalibration, and prints the audit result.
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
from forge.config import load_recalibration_config, load_scoring_config  # noqa: E402
from forge.db.base import create_db_engine, make_session_factory  # noqa: E402
from forge.db.models import DecisionType, OutcomeType  # noqa: E402
from forge.output.decisions import capture_decision, capture_outcome  # noqa: E402
from forge.recalibration import run_recalibration  # noqa: E402
from forge.repository import save_asset  # noqa: E402
from synthetic.assets import minimal_grounded_bundle  # noqa: E402


class _Score:
    def __init__(self, value):
        self.value, self.coverage = value, 0.75


def _record(session, score, outcome):
    asset = save_asset(session, minimal_grounded_bundle())
    capture_decision(session, asset, decision=DecisionType.sprint, decided_by="committee",
                     score=_Score(score))
    capture_outcome(session, asset, outcome=outcome, recorded_by="ops")


def main() -> int:
    pg = start_embedded()
    os.environ["FORGE_DATABASE_URL"] = pg.url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        session = make_session_factory(create_db_engine(pg.url))()

        # A quarter of history: winners scored high, losers scored low.
        _record(session, 0.88, OutcomeType.spun_out)
        _record(session, 0.81, OutcomeType.licensed)
        _record(session, 0.74, OutcomeType.in_progress)  # not terminal -> excluded
        _record(session, 0.29, OutcomeType.parked)
        _record(session, 0.18, OutcomeType.abandoned)

        result = run_recalibration(
            session,
            scoring_config=load_scoring_config("config/scoring.yaml"),
            config=load_recalibration_config("config/recalibration.yaml"),
        )

        print(result.summary())
        print(f"  mean score of winners : {result.mean_score_good:.2f}")
        print(f"  mean score of losers  : {result.mean_score_bad:.2f}")
        print(f"  separation            : {result.separation:+.2f}")
        print(f"  suggested cutoff      : {result.recommended_cutoff:.2f}")
        print(f"  logged as             : {result.id}")
        session.close()
        return 0
    finally:
        pg.stop()


if __name__ == "__main__":
    raise SystemExit(main())
