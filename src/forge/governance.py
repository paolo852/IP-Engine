"""Governance (cross-cutting): RBAC, data residency, and data protection.

These are enforced at the engine's seams — the CLI authorizes each command, the
asset-store guards what may be persisted in development (GDPR / rule 4), and the
pipeline checks hosted-LLM residency. The policy itself is config (config/
governance.yaml); this module is the deterministic logic that applies it.

Humans and roles decide; the engine enforces the agreed policy and fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import GovernanceConfig

# The complete permission vocabulary. Roles (in config) grant subsets; 'admin'
# implies all of them.
PERMISSIONS = frozenset(
    {
        "view",
        "ingest",
        "run_pipeline",
        "decide",
        "record_outcome",
        "recalibrate",
        "delete_asset",
        "migrate",
        # Relationship-graph & need-matching domain (T9+). Company-level graph
        # access is separate from — and looser than — the restricted contact
        # sub-record, which holds personal data.
        "view_graph",
        "view_contacts",
        "match",
        "validate",
        "record_trl",
        "admin",
    }
)


class GovernanceError(Exception):
    """Base class for governance failures."""


class AuthorizationError(GovernanceError):
    """A principal lacks the permission required for an action (RBAC)."""


class DataProtectionError(GovernanceError):
    """Storing this data is not permitted under the current mode (GDPR / rule 4)."""


class ResidencyError(GovernanceError):
    """A hosted-LLM call would breach the data-residency policy (EU-hosting)."""


class ContactAccessError(GovernanceError):
    """Revealing a personal contact record is not permitted (dev safety / GDPR)."""


@dataclass(frozen=True)
class Principal:
    """Who is acting, and in what role."""

    name: str
    role: str


def permissions_for(role: str, config: GovernanceConfig) -> frozenset[str]:
    """Resolve a role's effective permissions ('admin' expands to all)."""
    if role not in config.roles:
        raise AuthorizationError(f"unknown role {role!r}")
    granted = set(config.roles[role])
    if "admin" in granted:
        return PERMISSIONS
    return frozenset(granted)


def authorize(principal: Principal, permission: str, config: GovernanceConfig) -> None:
    """Raise AuthorizationError unless ``principal`` holds ``permission``."""
    if permission not in permissions_for(principal.role, config):
        raise AuthorizationError(
            f"{principal.name} (role={principal.role}) is not permitted to {permission!r}"
        )


def assert_storable(asset_type: str, licence: str, config: GovernanceConfig) -> None:
    """Guard the asset-store seam against unpermitted data (GDPR / rule 4).

    In development only synthetic/public data may be stored, and personal/
    confidential asset types (e.g. invention disclosures) are out of scope — they
    enter later under production_eu, with GDPR / EU-hosting protocols.
    """
    if config.mode != "development":
        return  # production_eu: real data permitted under its protocols
    if asset_type in config.restricted_asset_types:
        raise DataProtectionError(
            f"asset type {asset_type!r} may carry personal/confidential data and is "
            "not permitted in development (needs production_eu under GDPR/EU-hosting)"
        )
    if licence not in config.dev_allowed_licences:
        raise DataProtectionError(
            f"licence {licence!r} is not permitted in development "
            f"(synthetic/public only: {list(config.dev_allowed_licences)})"
        )


def assert_contact_access(
    principal: Principal, config: GovernanceConfig, *, lawful_basis: bool
) -> None:
    """Guard the restricted contact sub-record (person/email) — the graph's
    highest-sensitivity, personal data. Three gates, all must pass:

    1. RBAC — the principal must hold ``view_contacts`` (stricter than the
       company-level ``view_graph``).
    2. Dev safety (rule 6) — contacts are disabled in development unless the
       policy explicitly enables them; the dev graph is synthetic and holds no
       real personal data.
    3. GDPR lawful basis — when the policy requires it, a lawful basis must be
       recorded for this contact before person/email may be revealed.

    Raises AuthorizationError or ContactAccessError; returns None if all pass.
    """
    authorize(principal, "view_contacts", config)  # gate 1 (raises AuthorizationError)
    if config.mode == "development" and not config.contacts_enabled_in_dev:
        raise ContactAccessError(
            "contact details are disabled in development (synthetic graph only, "
            "no real personal data — rule 6)"
        )
    if config.contacts_require_lawful_basis and not lawful_basis:
        raise ContactAccessError(
            "no lawful basis recorded for this contact — person/email may not be "
            "revealed (GDPR)"
        )


def contacts_visible(
    principal: Principal, config: GovernanceConfig, *, lawful_basis: bool
) -> bool:
    """Non-raising counterpart for the UI. Contacts are hidden by DEFAULT —
    company-level matching must work without them — so this returns True only when
    every contact-access gate passes."""
    try:
        assert_contact_access(principal, config, lawful_basis=lawful_basis)
        return True
    except GovernanceError:
        return False


def check_llm_residency(base_url: str | None, config: GovernanceConfig) -> tuple[bool, str]:
    """Return (ok, reason) for whether a hosted-LLM endpoint meets EU-hosting."""
    if not config.require_eu_hosting:
        return True, "EU-hosting not required by policy"
    if base_url and any(marker in base_url.lower() for marker in config.eu_host_markers):
        return True, "LLM endpoint is EU-hosted"
    return False, "LLM endpoint is not EU-hosted (set llm base_url to an EU region)"


def assert_residency(base_url: str | None, config: GovernanceConfig) -> tuple[bool, str]:
    """Raise ResidencyError if EU-hosting is required and unmet; else return (ok, reason)."""
    ok, reason = check_llm_residency(base_url, config)
    if not ok and config.require_eu_hosting:
        raise ResidencyError(reason)
    return ok, reason
