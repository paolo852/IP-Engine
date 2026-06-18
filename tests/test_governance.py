"""Governance: RBAC, data-protection (GDPR / rule 4), and EU-hosting residency."""

from __future__ import annotations

import pytest

from forge.config import GovernanceConfig, load_governance_config
from forge.db.models import Asset, AssetType, Licence, Source
from forge.governance import (
    AuthorizationError,
    DataProtectionError,
    Principal,
    ResidencyError,
    assert_residency,
    assert_storable,
    authorize,
    check_llm_residency,
    permissions_for,
)
from forge.repository import AssetBundle, ProvenanceEntry, save_asset

from .synthetic.assets import synthetic_patent_bundle

REPO = load_governance_config("config/governance.yaml")


def gov(**over) -> GovernanceConfig:
    base = dict(
        mode="development",
        restricted_asset_types=("disclosure",),
        dev_allowed_licences=("free", "public", "synthetic"),
        require_eu_hosting=False,
        eu_host_markers=("eu.", ".eu/"),
        roles={"viewer": ("view",), "analyst": ("view", "ingest"), "admin": ("admin",)},
    )
    base.update(over)
    return GovernanceConfig(**base)


# -- RBAC -------------------------------------------------------------------
def test_admin_role_implies_all_permissions():
    perms = permissions_for("admin", REPO)
    assert {"view", "decide", "recalibrate", "migrate"} <= perms


def test_role_grants_only_its_permissions():
    authorize(Principal("v", "viewer"), "view", REPO)  # ok
    with pytest.raises(AuthorizationError, match="not permitted to 'decide'"):
        authorize(Principal("v", "viewer"), "decide", REPO)


def test_committee_can_decide_but_not_ingest():
    authorize(Principal("c", "committee"), "decide", REPO)
    with pytest.raises(AuthorizationError):
        authorize(Principal("c", "committee"), "ingest", REPO)


def test_unknown_role_is_rejected():
    with pytest.raises(AuthorizationError, match="unknown role"):
        authorize(Principal("x", "superuser"), "view", REPO)


# -- data protection (GDPR / rule 4) ----------------------------------------
def test_dev_blocks_restricted_asset_types():
    with pytest.raises(DataProtectionError, match="disclosure"):
        assert_storable("disclosure", "synthetic", gov())


def test_dev_blocks_non_public_licences():
    with pytest.raises(DataProtectionError, match="licence"):
        assert_storable("patent", "licensed_dealroom", gov())


def test_dev_allows_synthetic_public_assets():
    assert_storable("patent", "synthetic", gov()) is None
    assert_storable("patent", "free", gov()) is None


def test_production_eu_permits_restricted_data():
    assert_storable("disclosure", "internal", gov(mode="production_eu")) is None


def test_save_asset_enforces_policy(session):
    # Synthetic patent (synthetic licence) is storable in development.
    save_asset(session, synthetic_patent_bundle(), policy=gov())

    # A disclosure asset is blocked before anything is written.
    src = Source(source_type="internal", licence=Licence.internal, locator="x")
    asset = Asset(asset_type=AssetType.disclosure, source_layer="L1", title="secret idea")
    bundle = AssetBundle(asset=asset, provenance=[ProvenanceEntry("title", src)])
    with pytest.raises(DataProtectionError):
        save_asset(session, bundle, policy=gov())
    session.rollback()


# -- residency (EU-hosting) -------------------------------------------------
def test_residency_not_required_is_ok():
    ok, _ = check_llm_residency("https://api.anthropic.com", gov(require_eu_hosting=False))
    assert ok


def test_residency_required_accepts_eu_endpoint():
    ok, _ = check_llm_residency(
        "https://eu.gateway.example/anthropic", gov(require_eu_hosting=True)
    )
    assert ok


def test_residency_required_rejects_non_eu_endpoint():
    cfg = gov(require_eu_hosting=True)
    ok, reason = check_llm_residency("https://api.anthropic.com", cfg)
    assert not ok and "not EU-hosted" in reason
    with pytest.raises(ResidencyError):
        assert_residency("https://api.anthropic.com", cfg)


def test_repo_governance_config_is_valid():
    assert REPO.mode == "development"
    assert "viewer" in REPO.roles


def test_governance_rejects_bad_mode(tmp_path):
    p = tmp_path / "governance.yaml"
    p.write_text("mode: staging\nrbac:\n  roles:\n    admin: [admin]\n")
    with pytest.raises(Exception, match="mode"):
        load_governance_config(p)
