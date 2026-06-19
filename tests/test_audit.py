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
