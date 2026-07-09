"""T11: end-to-end need matching over stored profile + graph (persisted, idempotent)."""

from __future__ import annotations

from pathlib import Path

from forge.config import load_needs_config
from forge.connectors.cordis.parser import parse_project
from forge.db.models import Track
from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.graph import build_layer0
from forge.matching import get_need_hypotheses, run_matching
from forge.repository import save_asset, save_profile

from ..synthetic.assets import synthetic_patent_bundle

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CFG = load_needs_config("config/needs.yaml")


def _photonics_profile() -> AssetProfile:
    def g(name, value, field, **extra):
        return GroundedField(name=name, value=value, quote="q", source_field=field, **extra)

    return AssetProfile(
        problem=g("problem", "inter-chip energy", "abstract"),
        solution=g("solution", "micro-ring modulator", "claims_or_description"),
        applications=[
            g(
                "application[0]",
                "co-packaged optics",
                "abstract",
                end_customer="data centre operators",
                use_case="rack-scale interconnect",
                industry_terms=["photonics", "optical interconnect"],
            )
        ],
        query_terms=["photonics"],
        model="m",
        technology_summary="A silicon photonics interconnect",
    )


def _seed(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _photonics_profile())
    build_layer0(session, parse_project((FIXTURES / "cordis_project_single.json").read_bytes()))
    session.commit()
    return asset


def test_run_matching_persists_a_grounded_producer_hypothesis(session):
    asset = _seed(session)
    run_matching(session, asset, cfg=CFG)

    rows = get_need_hypotheses(session, asset.id)
    # Aurora Photonics matches on "photonics"; Borealis / the university do not.
    assert len(rows) == 1
    h = rows[0]
    assert h.company.name == "Aurora Photonics GmbH"
    assert h.track is Track.producer
    assert "unvalidated" in h.hypothesised_need.lower()
    # grounded back to the CORDIS project tie.
    assert any(e.get("ref") == "cordis:project:101001234" for e in h.evidence)


def test_re_matching_replaces_not_duplicates(session):
    asset = _seed(session)
    run_matching(session, asset, cfg=CFG)
    run_matching(session, asset, cfg=CFG)  # second pass
    assert len(get_need_hypotheses(session, asset.id)) == 1


def test_no_graph_means_no_hypotheses(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _photonics_profile())
    session.commit()
    run_matching(session, asset, cfg=CFG)  # empty graph
    assert get_need_hypotheses(session, asset.id) == []
