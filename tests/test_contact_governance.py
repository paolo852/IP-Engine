"""T9: privacy scaffolding for the Relationship Graph — contact isolation + GDPR.

Company-level graph access (view_graph) is separate from and looser than the
restricted contact sub-record (view_contacts), which holds personal data and is
gated by dev-safety (rule 6) and a GDPR lawful basis. Contacts are hidden by
default; matching must work company-level without them.
"""

from __future__ import annotations

import pytest

from forge.config import GovernanceConfig, load_governance_config
from forge.governance import (
    PERMISSIONS,
    AuthorizationError,
    ContactAccessError,
    Principal,
    assert_contact_access,
    contacts_visible,
    permissions_for,
)

REPO = load_governance_config("config/governance.yaml")


def gov(**over) -> GovernanceConfig:
    base = dict(
        mode="development",
        restricted_asset_types=(),
        dev_allowed_licences=("synthetic",),
        require_eu_hosting=False,
        eu_host_markers=(),
        roles={
            "viewer": ("view", "view_graph"),
            "analyst": ("view", "view_graph", "match"),
            "contacts_officer": ("view_contacts",),
            "admin": ("admin",),
        },
    )
    base.update(over)
    return GovernanceConfig(**base)


def test_new_graph_permissions_exist():
    assert {"view_graph", "view_contacts", "match", "validate", "record_trl"} <= PERMISSIONS


def test_graph_view_is_separate_from_contact_view():
    perms = permissions_for("analyst", gov())
    assert "view_graph" in perms and "view_contacts" not in perms


def test_contacts_need_the_view_contacts_permission():
    # An analyst (graph, no contacts) is refused even if contacts are enabled.
    with pytest.raises(AuthorizationError):
        assert_contact_access(
            Principal("a", "analyst"), gov(contacts_enabled_in_dev=True), lawful_basis=True
        )


def test_contacts_blocked_in_dev_even_with_permission():
    with pytest.raises(ContactAccessError, match="development"):
        assert_contact_access(Principal("o", "contacts_officer"), gov(), lawful_basis=True)


def test_contacts_require_a_lawful_basis_outside_dev():
    cfg = gov(mode="production_eu")  # dev gate no longer applies
    with pytest.raises(ContactAccessError, match="lawful basis"):
        assert_contact_access(Principal("o", "contacts_officer"), cfg, lawful_basis=False)
    assert assert_contact_access(Principal("o", "contacts_officer"), cfg, lawful_basis=True) is None


def test_lawful_basis_can_be_waived_by_config():
    cfg = gov(mode="production_eu", contacts_require_lawful_basis=False)
    assert assert_contact_access(Principal("o", "contacts_officer"), cfg, lawful_basis=False) is None


def test_contacts_hidden_by_default():
    # Hidden for a graph-only role, and for a contacts officer while in dev.
    assert contacts_visible(Principal("a", "analyst"), gov(), lawful_basis=True) is False
    assert contacts_visible(Principal("o", "contacts_officer"), gov(), lawful_basis=True) is False
    # Only when every gate passes (production + permission + lawful basis).
    cfg = gov(mode="production_eu")
    assert contacts_visible(Principal("o", "contacts_officer"), cfg, lawful_basis=True) is True
    assert contacts_visible(Principal("o", "contacts_officer"), cfg, lawful_basis=False) is False


# -- the shipped policy -------------------------------------------------------
def test_repo_policy_grants_graph_view_broadly_but_isolates_contacts():
    assert "view_graph" in permissions_for("viewer", REPO)
    assert "view_graph" in permissions_for("committee", REPO)
    assert "view_contacts" not in permissions_for("committee", REPO)
    assert "view_contacts" not in permissions_for("analyst", REPO)
    assert "view_contacts" in permissions_for("admin", REPO)  # admin implies all


def test_repo_policy_disables_contacts_in_dev_by_default():
    assert REPO.mode == "development"
    assert REPO.contacts_enabled_in_dev is False
    assert REPO.contacts_require_lawful_basis is True
    # Even admin cannot reveal a contact in the shipped dev policy.
    assert contacts_visible(Principal("root", "admin"), REPO, lawful_basis=True) is False
