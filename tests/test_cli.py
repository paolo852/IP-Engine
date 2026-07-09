"""CLI smoke tests for the DB-backed, credential-free commands."""

from __future__ import annotations

from datetime import date

from forge.cli import main
from forge.db.models import AssetType, OutcomeType
from forge.dormancy import assess_asset
from forge.config import (
    load_dormancy_config,
    load_organisation_config,
    load_scoring_config,
)
from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.output.decisions import capture_decision, capture_outcome
from forge.repository import save_asset, save_profile
from forge.db.models import DecisionType

from .synthetic.assets import synthetic_patent_bundle


class _Score:
    def __init__(self, value):
        self.value, self.coverage = value, 0.75


def _profile() -> AssetProfile:
    def g(name, value, quote, field):
        return GroundedField(name=name, value=value, quote=quote, source_field=field)

    return AssetProfile(
        problem=g("problem", "photonic optical interconnect energy", "reducing inter-chip energy per bit", "abstract"),
        solution=g("solution", "micro-ring modulator waveguide", "micro-ring modulator array coupled to a silicon waveguide", "claims_or_description"),
        applications=[g("application[0]", "edge AI", "photonic interconnect", "title")],
        query_terms=["optical interconnect", "photonics"],
        model="m",
    )


def test_assets_lists_saved_assets(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())
    assert main(["assets"]) == 0
    out = capsys.readouterr().out
    assert str(asset.id) in out and "photonic" in out.lower()


def test_dormancy_all_reports_verdict(session, capsys):
    save_asset(session, synthetic_patent_bundle())
    assert main(["dormancy", "--all"]) == 0
    assert "candidate" in capsys.readouterr().out


def test_decide_then_dashboard(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())

    assert main(["decide", str(asset.id), "sprint", "--by", "committee@org"]) == 0
    assert "recorded decision sprint" in capsys.readouterr().out

    assert main(["dashboard"]) == 0
    assert "sprint" in capsys.readouterr().out


def test_outcome_command(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())
    main(["decide", str(asset.id), "license", "--by", "c"])
    capsys.readouterr()
    assert main(["outcome", str(asset.id), "licensed", "--by", "ops"]) == 0
    assert "recorded outcome licensed" in capsys.readouterr().out


def test_cluster_command_groups_profiled_assets(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())
    capture_decision(session, asset, decision=DecisionType.sprint, decided_by="c",
                     score=_Score(0.8))
    assert main(["cluster"]) == 0
    out = capsys.readouterr().out
    assert "photonics" in out.lower()


def test_recalibrate_command(session, capsys):
    # Two winners high, two losers low -> well calibrated.
    for sc, oc in [(0.85, OutcomeType.spun_out), (0.80, OutcomeType.licensed),
                   (0.20, OutcomeType.abandoned), (0.30, OutcomeType.parked)]:
        a = save_asset(session, synthetic_patent_bundle())
        capture_decision(session, a, decision=DecisionType.sprint, decided_by="c", score=_Score(sc))
        capture_outcome(session, a, outcome=oc, recorded_by="ops")
    assert main(["recalibrate"]) == 0
    assert "well_calibrated" in capsys.readouterr().out


def test_graph_lists_companies(session, capsys):
    from forge.connectors.cordis.parser import parse_project
    from forge.graph import build_layer0
    from pathlib import Path

    fixture = Path(__file__).resolve().parent / "fixtures" / "cordis_project_single.json"
    build_layer0(session, parse_project(fixture.read_bytes()))
    session.commit()

    assert main(["graph"]) == 0
    out = capsys.readouterr().out
    assert "Aurora Photonics GmbH" in out and "collaborative_project" in out
    assert "SYNTHETIC UNIVERSITY" not in out  # the university is not a graph company


def test_graph_view_permission_allows_viewer(session, capsys, monkeypatch):
    monkeypatch.setenv("FORGE_ROLE", "viewer")  # viewer holds view_graph
    assert main(["graph"]) == 0


def test_hypotheses_cli_generates_and_lists(session, capsys):
    from pathlib import Path

    from forge.connectors.cordis.parser import parse_project
    from forge.enrichment.profiling import AssetProfile, GroundedField
    from forge.graph import build_layer0

    def g(name, value, field, **extra):
        return GroundedField(name=name, value=value, quote="q", source_field=field, **extra)

    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(
        session, asset,
        AssetProfile(
            problem=g("problem", "energy", "abstract"),
            solution=g("solution", "modulator", "claims_or_description"),
            applications=[g("application[0]", "co-packaged optics", "abstract",
                            end_customer="data centres", use_case="interconnect",
                            industry_terms=["photonics"])],
            query_terms=["photonics"], model="m", technology_summary="silicon photonics",
        ),
    )
    fixture = Path(__file__).resolve().parent / "fixtures" / "cordis_project_single.json"
    build_layer0(session, parse_project(fixture.read_bytes()))
    session.commit()

    assert main(["hypotheses", str(asset.id), "--generate"]) == 0
    out = capsys.readouterr().out
    assert "Aurora Photonics GmbH" in out and "unvalidated" in out.lower()


def test_company_lists_cli(session, capsys):
    from forge.db.models import Strength, Track
    from forge.graph import add_relationship, resolve_company
    from forge.matching import NeedHypothesisDraft, save_need_hypotheses
    from forge.db.models import RelationshipType

    asset = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH", country="DE")
    add_relationship(session, company, type=RelationshipType.collaborative_project,
                     source_layer=0, topic="PHOTON-EDGE", source_ref="cordis:project:1")
    session.flush()
    save_need_hypotheses(session, asset, [
        NeedHypothesisDraft(company_id=company.id, track=Track.producer, strength=Strength.medium,
                            hypothesised_need="Hypothesis (unvalidated): Aurora", evidence=[], rationale=""),
    ])
    session.commit()

    assert main(["company-lists", str(asset.id)]) == 0
    out = capsys.readouterr().out
    assert "PRODUCER" in out and "Aurora Photonics GmbH" in out and "related" in out


def test_validate_need_and_trl_cli(session, capsys):
    from forge.db.models import NeedOutcome, Track
    from forge.graph import resolve_company
    from forge.validation import confirmed_tracks, latest_trl_check

    asset = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    session.commit()

    assert main(["validate-need", str(asset.id), str(company.id), "producer",
                 "need_confirmed", "--by", "ops"]) == 0
    assert "recorded need validation" in capsys.readouterr().out
    assert confirmed_tracks(session, asset.id) == {Track.producer}

    assert main(["trl", str(asset.id), "6-9", "--prototype", "--by", "inv"]) == 0
    assert "high (~6-9)" in capsys.readouterr().out
    assert latest_trl_check(session, asset.id).trl_band == "6-9"

    # An unknown band is rejected, not stored.
    assert main(["trl", str(asset.id), "9-10"]) == 1


def test_route_cli_pending_then_ready(session, capsys):
    from forge.db.models import NeedOutcome, Track
    from forge.graph import resolve_company
    from forge.validation import record_need_validation, record_trl_check

    asset = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    session.commit()

    assert main(["route", str(asset.id)]) == 0
    assert "PENDING" in capsys.readouterr().out

    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    record_trl_check(session, asset, trl_band="6-9", recorded_by="inv")
    assert main(["route", str(asset.id)]) == 0
    assert "LICENSING" in capsys.readouterr().out


def test_trl_form_prints_questionnaire(capsys):
    assert main(["trl-form"]) == 0
    out = capsys.readouterr().out
    assert "TRL band" in out and "prototype" in out


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "FORGE Mining Engine CLI" in capsys.readouterr().out


def test_rbac_blocks_unauthorised_command(session, capsys, monkeypatch):
    import uuid

    monkeypatch.setenv("FORGE_ROLE", "viewer")  # viewer may not decide
    assert main(["decide", str(uuid.uuid4()), "sprint"]) == 1
    assert "not permitted to 'decide'" in capsys.readouterr().err


def test_rbac_allows_permitted_command(session, capsys, monkeypatch):
    save_asset(session, synthetic_patent_bundle())
    monkeypatch.setenv("FORGE_ROLE", "viewer")  # viewer may view
    assert main(["assets"]) == 0
    assert "photonic" in capsys.readouterr().out.lower()
