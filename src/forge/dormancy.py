"""L4 deterministic dormancy rules — config-driven and explainable.

Dormancy is a *deterministic* classification: given an asset and an as-of date,
the same inputs always yield the same verdict. There is no ML here (rule 2's
spirit) and no hard-coded thresholds — every number and marker comes from
``DormancyConfig`` (rule 3).

Each assessment is **explainable**: it records, per condition, the asset field it
read, the observed value, and the threshold. Because those asset fields are
themselves grounded (provenance), a dormancy verdict is fully auditable. A
condition whose input is missing is reported as ``unknown`` rather than guessed,
so the Engine never asserts dormancy it cannot support (grounding rule, rule 1).
Humans decide; this only flags and evidences candidates.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .config import DormancyConfig, OrganisationConfig
from .db.models import Asset, AssetType

DAYS_PER_YEAR = 365.25

# Field-name conventions (schema-level, not thresholds): the key_dates entries
# consulted, in priority order, to date an asset.
PATENT_AGE_DATE_KEYS = ("filing_date", "priority_date", "grant_date", "publication_date")
PROJECT_END_DATE_KEYS = ("end_date", "project_end_date", "completion_date")

# Fallback signal markers if config omits them (kept in sync with config/dormancy.yaml).
_DEFAULT_CLEAR_VALUES = ("", "none", "none recorded", "no encumbrances", "unencumbered")
_DEFAULT_EXPLOITATION_KEYS = (
    "exploitation_date",
    "licence_date",
    "license_date",
    "spinoff_date",
    "spin_off_date",
)


class Status(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass
class ConditionResult:
    """One rule condition: did it pass, on what evidence, against what threshold."""

    name: str
    status: Status
    detail: str
    field: str | None = None  # the asset field this condition read (audit trail)
    observed: Any = None
    threshold: Any = None


@dataclass
class DormancyAssessment:
    """The explainable outcome of evaluating one asset against one ruleset."""

    ruleset: str
    as_of: date
    conditions: list[ConditionResult] = field(default_factory=list)

    @property
    def determinate(self) -> bool:
        """True only if every condition had enough input to decide."""
        return bool(self.conditions) and all(
            c.status is not Status.UNKNOWN for c in self.conditions
        )

    @property
    def is_candidate(self) -> bool:
        """A dormancy candidate iff every condition passes (and none is unknown)."""
        return bool(self.conditions) and all(
            c.status is Status.PASS for c in self.conditions
        )

    def names_with(self, status: Status) -> list[str]:
        return [c.name for c in self.conditions if c.status is status]

    def verdict(self) -> str:
        if self.is_candidate:
            return "dormancy candidate"
        if not self.determinate:
            return "indeterminate"
        return "not a candidate"

    def explanation(self) -> str:
        marks = {Status.PASS: "PASS", Status.FAIL: "FAIL", Status.UNKNOWN: "????"}
        lines = [f"{self.ruleset}: {self.verdict()} (as of {self.as_of.isoformat()})"]
        for c in self.conditions:
            lines.append(f"  [{marks[c.status]}] {c.name}: {c.detail}")
        return "\n".join(lines)


# -- signal derivation (config-driven) --------------------------------------
def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _first_date(key_dates: dict | None, keys) -> tuple[date | None, str | None]:
    if not key_dates:
        return None, None
    for key in keys:
        parsed = _parse_date(key_dates.get(key))
        if parsed is not None:
            return parsed, key
    return None, None


def _years_between(then: date, as_of: date) -> float:
    return (as_of - then).days / DAYS_PER_YEAR


def _clear_values(signals: dict) -> set[str]:
    values = signals.get("encumbrance_clear_values", _DEFAULT_CLEAR_VALUES)
    return {str(v).strip().lower() for v in values}


def _has_active_encumbrance(asset: Asset, signals: dict) -> bool:
    """An active licence/option/spin-off is any non-"clear" encumbrance value.

    Absence of a recorded encumbrance is treated as "no active licence" — the
    asset is flagged for a human to verify, not auto-decided.
    """
    if asset.encumbrances is None:
        return False
    return asset.encumbrances.strip().lower() not in _clear_values(signals)


def _has_exploitation_event(asset: Asset, signals: dict) -> bool:
    keys = signals.get("exploitation_event_date_keys", _DEFAULT_EXPLOITATION_KEYS)
    key_dates = asset.key_dates or {}
    if any(key_dates.get(k) for k in keys):
        return True
    return _has_active_encumbrance(asset, signals)


def _is_org_owned(asset: Asset, org: OrganisationConfig) -> bool:
    parties = list(asset.owners or []) + list(asset.co_owners or [])
    return any(org.matches(p) for p in parties)


# -- range helper -----------------------------------------------------------
def _range_condition(
    name: str,
    value: float | None,
    lo: float,
    hi: float,
    *,
    field_name: str,
    unit_detail: str,
) -> ConditionResult:
    if value is None:
        return ConditionResult(
            name, Status.UNKNOWN, f"{unit_detail}: no usable date",
            field=field_name, threshold=[lo, hi],
        )
    status = Status.PASS if lo <= value <= hi else Status.FAIL
    return ConditionResult(
        name, status, f"{unit_detail} {value:.1f} vs [{lo}, {hi}]",
        field=field_name, observed=round(value, 2), threshold=[lo, hi],
    )


# -- rulesets ---------------------------------------------------------------
def assess_patent(asset: Asset, config: DormancyConfig, *, as_of: date) -> DormancyAssessment:
    pc = config.patents
    signals = config.signals
    conditions: list[ConditionResult] = []

    ref_date, ref_key = _first_date(asset.key_dates, PATENT_AGE_DATE_KEYS)
    age = _years_between(ref_date, as_of) if ref_date else None
    conditions.append(
        _range_condition(
            "age_in_range", age, pc["min_age_years"], pc["max_age_years"],
            field_name=f"key_dates.{ref_key}" if ref_key else "key_dates",
            unit_detail="age (years)",
        )
    )

    allowed = [str(s).lower() for s in pc.get("fee_status_in", [])]
    if not asset.fee_status:
        conditions.append(
            ConditionResult("fee_status_eligible", Status.UNKNOWN, "fee_status not set",
                            field="fee_status", threshold=allowed)
        )
    else:
        ok = asset.fee_status.strip().lower() in allowed
        conditions.append(
            ConditionResult(
                "fee_status_eligible", Status.PASS if ok else Status.FAIL,
                f"fee_status {asset.fee_status!r} in {allowed}",
                field="fee_status", observed=asset.fee_status, threshold=allowed,
            )
        )

    if pc.get("require_no_active_licence", False):
        active = _has_active_encumbrance(asset, signals)
        conditions.append(
            ConditionResult(
                "no_active_licence", Status.FAIL if active else Status.PASS,
                f"encumbrances={asset.encumbrances!r} -> "
                + ("active licence/option/spin-off" if active else "none active"),
                field="encumbrances", observed=asset.encumbrances,
            )
        )

    return DormancyAssessment("patents", as_of, conditions)


def assess_project_result(
    asset: Asset,
    config: DormancyConfig,
    *,
    as_of: date,
    org: OrganisationConfig | None,
) -> DormancyAssessment:
    rc = config.project_results
    signals = config.signals
    conditions: list[ConditionResult] = []

    end_date, end_key = _first_date(asset.key_dates, PROJECT_END_DATE_KEYS)
    years = _years_between(end_date, as_of) if end_date else None
    conditions.append(
        _range_condition(
            "ended_in_window", years,
            rc["min_years_since_end"], rc["max_years_since_end"],
            field_name=f"key_dates.{end_key}" if end_key else "key_dates",
            unit_detail="years since end",
        )
    )

    if rc.get("require_no_exploitation_event", False):
        exploited = _has_exploitation_event(asset, signals)
        conditions.append(
            ConditionResult(
                "no_exploitation_event", Status.FAIL if exploited else Status.PASS,
                "exploitation event since project end"
                if exploited else "no exploitation event recorded",
                field="key_dates/encumbrances", observed=exploited,
            )
        )

    if rc.get("require_org_ownership", False):
        if org is None:
            conditions.append(
                ConditionResult("org_ownership", Status.UNKNOWN,
                                "no organisation config provided", field="owners")
            )
        else:
            owned = _is_org_owned(asset, org)
            conditions.append(
                ConditionResult(
                    "org_ownership", Status.PASS if owned else Status.FAIL,
                    f"{org.name} is owner/co-owner" if owned
                    else f"{org.name} not among owners/co-owners",
                    field="owners",
                    observed=list(asset.owners or []) + list(asset.co_owners or []),
                )
            )

    return DormancyAssessment("project_results", as_of, conditions)


def assess_asset(
    asset: Asset,
    config: DormancyConfig,
    *,
    as_of: date | None = None,
    org: OrganisationConfig | None = None,
) -> DormancyAssessment:
    """Dispatch to the ruleset for the asset's type. ``as_of`` defaults to today."""
    as_of = as_of or date.today()
    if asset.asset_type is AssetType.patent:
        return assess_patent(asset, config, as_of=as_of)
    if asset.asset_type is AssetType.project_result:
        return assess_project_result(asset, config, as_of=as_of, org=org)
    raise ValueError(f"no dormancy ruleset defined for asset_type {asset.asset_type.value!r}")
