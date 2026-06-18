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


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "FORGE Mining Engine CLI" in capsys.readouterr().out
