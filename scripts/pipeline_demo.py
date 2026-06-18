"""End-to-end demo: ingest -> pipeline -> committee decision -> dashboard.

    python scripts/pipeline_demo.py

Self-contained: boots a throwaway PostgreSQL, migrates it, saves a synthetic
asset, runs the whole pipeline (dormancy + profiling + 4 streams + corroboration
+ scoring + grounded brief) with fake provider/clients, records a committee
decision from the routing, and prints the ranked dashboard. No network/LLM/keys.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from _pg import start_embedded  # noqa: E402
from enrichment.fakes import FakeProvider, profile_json  # noqa: E402
from forge.db.base import create_db_engine, make_session_factory  # noqa: E402
from forge.db.models import DecisionType  # noqa: E402
from forge.output.decisions import capture_decision, dashboard  # noqa: E402
from forge.pipeline import Pipeline, PipelineConfig  # noqa: E402
from forge.repository import get_evidence, get_profile, save_asset  # noqa: E402
from forge.streams.corroboration import Routing  # noqa: E402
from forge.streams.s1_funding import FundingSearch  # noqa: E402
from forge.streams.s2_patents import CitingDoc, SearchHit, SearchResult, YearCount  # noqa: E402
from streams.fakes import FakeS2Client  # noqa: E402
from synthetic.assets import synthetic_patent_bundle  # noqa: E402

ROUTING_TO_DECISION = {
    Routing.SPRINT: DecisionType.sprint,
    Routing.LICENCE_OR_PARK: DecisionType.license,
    Routing.WATCH: DecisionType.hold,
    Routing.PARK: DecisionType.park,
}


class FakeS1Client:
    def search_funding(self, query, *, years):
        return FundingSearch(total_amount_eur=22_000_000.0, round_count=6,
                             investors=["VC One", "VC Two", "Sovereign Tech Fund"])


def main() -> int:
    pg = start_embedded()
    os.environ["FORGE_DATABASE_URL"] = pg.url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        session = make_session_factory(create_db_engine(pg.url))()

        asset = save_asset(session, synthetic_patent_bundle())
        provider = FakeProvider(profile_json(
            problem=("High energy per bit in photonic interconnects",
                     "reducing inter-chip energy per bit for edge inference workloads"),
            solution=("A micro-ring modulator optical interconnect",
                      "micro-ring modulator array coupled to a silicon waveguide"),
            applications=[("Edge AI accelerators", "photonic interconnect for edge AI accelerators")],
            query_terms=["optical interconnect", "edge inference"],
        ))
        pipe = Pipeline(
            PipelineConfig.from_files(as_of=date(2025, 1, 1)),
            provider,
            s2_client=FakeS2Client(
                search=SearchResult(total=45, hits=[SearchHit("EP111A1", relevance=0.8)]),
                year_counts=[YearCount(2022, 8), YearCount(2023, 11), YearCount(2024, 15)],
                citing=[CitingDoc("EP900A1", "Acme"), CitingDoc("EP901A1", "BetaCo")],
            ),
            s1_client=FakeS1Client(),
        )

        report = pipe.run(session, [asset.id])
        r = report.results[0]

        print(f"== pipeline: {report.summary()} ==\n")
        print(r.dormancy.explanation(), "\n")
        print(r.corroboration.explanation(), "\n")
        print(r.score.breakdown(), "\n")
        print(f"persisted: profile={get_profile(session, asset.id) is not None}, "
              f"evidence rows={len(get_evidence(session, asset.id))}\n")

        # The committee reviews the brief and decides (here, from the routing).
        capture_decision(
            session, asset,
            decision=ROUTING_TO_DECISION[r.corroboration.routing],
            decided_by="committee@org",
            score=r.score, corroboration=r.corroboration,
            rationale=r.corroboration.rationale,
        )

        print("== committee dashboard ==")
        for row in dashboard(session):
            score = f"{row.engine_score:.2f}" if row.engine_score is not None else "  -  "
            print(f"  {score}  {row.engine_routing or '-':<14} {row.decision or 'pending':<8} "
                  f"{(row.title or '')[:42]}")
        session.close()
        return 0
    finally:
        pg.stop()


if __name__ == "__main__":
    raise SystemExit(main())
