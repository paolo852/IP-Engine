"""L4 dormancy rules: deterministic, config-driven, explainable — with edges."""

from __future__ import annotations

from datetime import date

import pytest

from forge.config import (
    DormancyConfig,
    OrganisationConfig,
    load_dormancy_config,
    load_organisation_config,
)
from forge.db.models import Asset, AssetType
from forge.dormancy import Status, assess_asset, assess_patent, assess_project_result

AS_OF = date(2025, 1, 1)
CONFIG = load_dormancy_config("config/dormancy.yaml")
ORG = load_organisation_config("config/organisation.yaml")


def patent(**kw) -> Asset:
    base = dict(asset_type=AssetType.patent, source_layer="L1.synthetic")
    base.update(kw)
    return Asset(**base)


def project(**kw) -> Asset:
    base = dict(asset_type=AssetType.project_result, source_layer="L1.synthetic")
    base.update(kw)
    return Asset(**base)


# -- patents ----------------------------------------------------------------
def test_patent_in_range_eligible_unencumbered_is_candidate():
    a = patent(
        key_dates={"filing_date": "2020-01-01"},  # age 5y at AS_OF
        fee_status="lapsing",
        encumbrances="none recorded",
    )
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert result.is_candidate and result.determinate
    assert result.names_with(Status.PASS) == [
        "age_in_range",
        "fee_status_eligible",
        "no_active_licence",
    ]


def test_patent_too_young_fails_age():
    a = patent(key_dates={"filing_date": "2023-06-01"}, fee_status="paid")
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert not result.is_candidate
    assert "age_in_range" in result.names_with(Status.FAIL)


def test_patent_too_old_fails_age():
    a = patent(key_dates={"filing_date": "2010-01-01"}, fee_status="paid")
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert "age_in_range" in result.names_with(Status.FAIL)


def test_patent_ineligible_fee_status_fails():
    a = patent(key_dates={"filing_date": "2020-01-01"}, fee_status="granted")
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert "fee_status_eligible" in result.names_with(Status.FAIL)


def test_patent_with_active_licence_is_not_candidate():
    a = patent(
        key_dates={"filing_date": "2020-01-01"},
        fee_status="paid",
        encumbrances="exclusive licence to AcmeCo",
    )
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert "no_active_licence" in result.names_with(Status.FAIL)
    assert not result.is_candidate


def test_patent_missing_dates_is_indeterminate_not_candidate():
    a = patent(fee_status="paid", encumbrances=None)
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert "age_in_range" in result.names_with(Status.UNKNOWN)
    assert not result.determinate
    assert not result.is_candidate  # never assert dormancy we cannot support


def test_patent_missing_fee_status_is_unknown():
    a = patent(key_dates={"filing_date": "2020-01-01"})
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    assert "fee_status_eligible" in result.names_with(Status.UNKNOWN)


def test_patent_uses_priority_date_when_no_filing_date():
    a = patent(key_dates={"priority_date": "2019-01-01"}, fee_status="paid")
    result = assess_patent(a, CONFIG, as_of=AS_OF)
    age_cond = next(c for c in result.conditions if c.name == "age_in_range")
    assert age_cond.field == "key_dates.priority_date"
    assert age_cond.status is Status.PASS


# -- config-driven proof (rule 3) -------------------------------------------
def test_thresholds_come_from_config_not_code():
    a = patent(key_dates={"filing_date": "2020-01-01"}, fee_status="paid",
               encumbrances=None)
    assert assess_patent(a, CONFIG, as_of=AS_OF).is_candidate  # default 3..10

    stricter = DormancyConfig(
        patents={"min_age_years": 6, "max_age_years": 10, "fee_status_in": ["paid"]},
        project_results=CONFIG.project_results,
        signals=CONFIG.signals,
    )
    # Same asset (age 5) now fails because the window moved — purely via config.
    assert "age_in_range" in assess_patent(a, stricter, as_of=AS_OF).names_with(Status.FAIL)


# -- project results --------------------------------------------------------
def test_project_in_window_unexploited_org_owned_is_candidate():
    a = project(
        key_dates={"end_date": "2022-01-01"},  # 3y ago at AS_OF
        owners=["Synthetic Research Org"],
    )
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=ORG)
    assert result.is_candidate and result.determinate


def test_project_ended_too_long_ago_fails():
    a = project(key_dates={"end_date": "2018-01-01"}, owners=["Synthetic Research Org"])
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=ORG)
    assert "ended_in_window" in result.names_with(Status.FAIL)


def test_project_with_exploitation_event_fails():
    a = project(
        key_dates={"end_date": "2022-01-01", "licence_date": "2023-03-01"},
        owners=["Synthetic Research Org"],
    )
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=ORG)
    assert "no_exploitation_event" in result.names_with(Status.FAIL)


def test_project_not_org_owned_fails():
    a = project(key_dates={"end_date": "2022-01-01"}, owners=["Some Other Company"])
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=ORG)
    assert "org_ownership" in result.names_with(Status.FAIL)


def test_project_owned_via_co_owner_passes():
    a = project(
        key_dates={"end_date": "2022-01-01"},
        owners=["Some Other Company"],
        co_owners=["SRO"],
    )
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=ORG)
    assert "org_ownership" in result.names_with(Status.PASS)


def test_project_without_org_config_is_unknown_ownership():
    a = project(key_dates={"end_date": "2022-01-01"}, owners=["Synthetic Research Org"])
    result = assess_project_result(a, CONFIG, as_of=AS_OF, org=None)
    assert "org_ownership" in result.names_with(Status.UNKNOWN)
    assert not result.determinate


# -- dispatch + explainability ----------------------------------------------
def test_assess_asset_dispatches_by_type():
    pat = patent(key_dates={"filing_date": "2020-01-01"}, fee_status="paid")
    assert assess_asset(pat, CONFIG, as_of=AS_OF).ruleset == "patents"
    proj = project(key_dates={"end_date": "2022-01-01"}, owners=["SRO"])
    assert assess_asset(proj, CONFIG, as_of=AS_OF, org=ORG).ruleset == "project_results"


def test_assess_asset_rejects_unsupported_type():
    sw = Asset(asset_type=AssetType.software, source_layer="L1.synthetic", title="tool")
    with pytest.raises(ValueError, match="no dormancy ruleset"):
        assess_asset(sw, CONFIG, as_of=AS_OF)


def test_explanation_lists_every_condition_and_is_deterministic():
    a = patent(key_dates={"filing_date": "2020-01-01"}, fee_status="lapsing",
               encumbrances=None)
    first = assess_patent(a, CONFIG, as_of=AS_OF).explanation()
    second = assess_patent(a, CONFIG, as_of=AS_OF).explanation()
    assert first == second  # deterministic
    assert "dormancy candidate" in first
    for name in ("age_in_range", "fee_status_eligible", "no_active_licence"):
        assert name in first
