"""E11: the automated grounding audit — every stored claim traces to a source."""

from __future__ import annotations

from sqlalchemy import delete

from forge.cli import main
from forge.db.models import ProfileGrounding
from forge.enrichment.profiling import AssetProfile, GroundedField
from forge.output.audit import audit_asset, audit_store
from forge.repository import save_asset, save_profile

from .synthetic.assets import synthetic_patent_bundle
from .test_pipeline import pipeline


def _profile() -> AssetProfile:
    def g(name, value, quote, field):
        return GroundedField(name=name, value=value, quote=quote, source_field=field)

    return AssetProfile(
        problem=g("problem", "inter-chip energy", "reducing inter-chip energy per bit", "abstract"),
        solution=g("solution", "micro-ring modulator", "micro-ring modulator array", "claims_or_description"),
        applications=[g("application[0]", "edge AI", "edge AI accelerators", "title")],
        query_terms=["optical interconnect"],
        model="m",
    )


def test_audit_passes_for_a_fully_grounded_asset(session):
    asset = save_asset(session, synthetic_patent_bundle())
    pipeline().run(session, [asset.id])  # profile + evidence + score persisted

    a = audit_asset(session, asset.id)
    assert a is not None and a.ok, a.violations
    assert {"asset", "profile", "evidence"} <= {t.layer for t in a.traces}
    assert all(t.grounded for t in a.traces)
    assert a.grounded_count == a.claim_count


def test_audit_store_summary_reports_pass(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())

    store = audit_store(session)
    assert store.ok
    assert "PASS" in store.summary()
    assert store.claim_count > 0


def test_audit_missing_asset_returns_none(session):
    import uuid

    assert audit_asset(session, uuid.uuid4()) is None


def test_audit_flags_a_profile_statement_that_lost_its_grounding(session):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())
    # Simulate drift/corruption past the write-time gate: a grounding row vanishes.
    session.execute(delete(ProfileGrounding).where(ProfileGrounding.field_name == "solution"))
    session.commit()
    session.expire_all()  # audit normally runs in a fresh session (e.g. the CLI)

    a = audit_asset(session, asset.id)
    assert not a.ok
    assert any("solution" in v and "ungrounded" in v for v in a.violations)


# -- CLI gate ----------------------------------------------------------------
def test_audit_cli_passes_and_traces(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())

    assert main(["audit"]) == 0
    assert "PASS" in capsys.readouterr().out

    assert main(["audit", str(asset.id), "--trace"]) == 0
    out = capsys.readouterr().out
    assert "asset.title" in out and "←" in out


def test_audit_cli_exits_nonzero_on_violation(session, capsys):
    asset = save_asset(session, synthetic_patent_bundle())
    save_profile(session, asset, _profile())
    session.execute(delete(ProfileGrounding).where(ProfileGrounding.field_name == "problem"))
    session.commit()

    assert main(["audit"]) == 1
    assert "FAIL" in capsys.readouterr().out


# -- T16: extended audit (hypotheses, licence separation, graph grounding) ---
def _seed_matching(session):
    from pathlib import Path

    from forge.config import load_needs_config
    from forge.connectors.cordis.parser import parse_project
    from forge.enrichment.profiling import AssetProfile, GroundedField
    from forge.graph import build_layer0
    from forge.matching import run_matching
    from forge.repository import save_profile as _sp

    def g(n, v, f, **e):
        return GroundedField(name=n, value=v, quote="q", source_field=f, **e)

    asset = save_asset(session, synthetic_patent_bundle())
    _sp(session, asset, AssetProfile(
        problem=g("problem", "energy", "abstract"),
        solution=g("solution", "modulator", "claims_or_description"),
        applications=[g("application[0]", "co-packaged optics", "abstract",
                        end_customer="data centres", use_case="interconnect",
                        industry_terms=["photonics"])],
        query_terms=["photonics"], model="m", technology_summary="silicon photonics"))
    fixture = Path(__file__).resolve().parent / "fixtures" / "cordis_project_single.json"
    build_layer0(session, parse_project(fixture.read_bytes()))
    session.commit()
    run_matching(session, asset, cfg=load_needs_config("config/needs.yaml"))
    return asset


def test_audit_traces_grounded_need_hypotheses(session):
    asset = _seed_matching(session)
    a = audit_asset(session, asset.id)
    assert a.ok, a.violations
    hyp_traces = [t for t in a.traces if t.layer == "hypothesis"]
    assert hyp_traces and all(t.grounded for t in hyp_traces)
    assert any("cordis:project:101001234" in s for t in hyp_traces for s in t.sources)


def test_audit_flags_a_need_hypothesis_without_a_source(session):
    from forge.db.models import Strength, Track
    from forge.graph import resolve_company
    from forge.matching import NeedHypothesisDraft, save_need_hypotheses

    asset = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    session.flush()
    save_need_hypotheses(session, asset, [
        NeedHypothesisDraft(company_id=company.id, track=Track.producer,
                            strength=Strength.weak,
                            hypothesised_need="ungrounded", evidence=[], rationale=""),
    ])
    a = audit_asset(session, asset.id)
    assert not a.ok
    assert any("no source pointer" in v for v in a.violations)


def test_licence_separation_flags_asset_field_on_licensed_source(session):
    from forge.db.models import Asset, AssetType, Licence, Source
    from forge.output.audit import licence_separation_audit
    from forge.repository import AssetBundle, ProvenanceEntry

    src = Source(source_type="dealroom", licence=Licence.licensed_dealroom, locator="deal/1")
    asset = Asset(asset_type=AssetType.patent, source_layer="L1", title="licensed-backed title")
    save_asset(session, AssetBundle(asset=asset, provenance=[ProvenanceEntry("title", src)]))

    violations = licence_separation_audit(session)
    assert any("LICENSED" in v and "title" in v for v in violations)


def test_licence_separation_passes_for_synthetic_store(session):
    from forge.output.audit import licence_separation_audit

    save_asset(session, synthetic_patent_bundle())
    assert licence_separation_audit(session) == []


def test_graph_grounding_flags_public_tie_without_source_ref(session):
    from forge.db.models import RelationshipType
    from forge.graph import add_relationship, resolve_company
    from forge.output.audit import graph_grounding_audit

    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    add_relationship(session, company, type=RelationshipType.collaborative_project,
                     source_layer=0, topic="P", source_ref=None)  # public, ungrounded
    add_relationship(session, company, type=RelationshipType.other,
                     source_layer=2, topic="tacit", source_ref=None)  # tacit, exempt
    session.commit()
    violations = graph_grounding_audit(session)
    assert len(violations) == 1 and "layer 0" in violations[0]


def test_store_audit_includes_store_violations_and_cli_gate(session, capsys):
    from forge.cli import main
    from forge.db.models import Asset, AssetType, Licence, Source
    from forge.output.audit import audit_store
    from forge.repository import AssetBundle, ProvenanceEntry

    src = Source(source_type="dealroom", licence=Licence.licensed_dealroom, locator="deal/1")
    asset = Asset(asset_type=AssetType.patent, source_layer="L1", title="licensed title")
    save_asset(session, AssetBundle(asset=asset, provenance=[ProvenanceEntry("title", src)]))

    store = audit_store(session)
    assert not store.ok and store.store_violations
    assert "licence separation" in store.render().lower()

    assert main(["audit"]) == 1  # the gate fails on a store-wide violation
    assert "FAIL" in capsys.readouterr().out
