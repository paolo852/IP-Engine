"""T13: capture the two human validations that feed two-axis routing."""

from __future__ import annotations

import uuid

from forge.config import load_trl_config
from forge.db.models import NeedOutcome, Track
from forge.graph import resolve_company
from forge.repository import save_asset
from forge.validation import (
    build_questionnaire,
    confirmed_tracks,
    latest_need_validation,
    latest_trl_check,
    record_need_validation,
    record_trl_check,
    validate_band,
)

from ..synthetic.assets import synthetic_patent_bundle

TRL = load_trl_config("config/trl.yaml")


def _asset_and_company(session):
    asset = save_asset(session, synthetic_patent_bundle())
    company, _ = resolve_company(session, name="Aurora Photonics GmbH")
    session.commit()
    return asset, company


# -- NEED axis --------------------------------------------------------------
def test_latest_need_validation_wins(session):
    asset, company = _asset_and_company(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.no_response, validated_by="a")
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="b")
    latest = latest_need_validation(session, asset.id, company.id, Track.producer)
    assert latest.outcome is NeedOutcome.need_confirmed and latest.validated_by == "b"


def test_confirmed_tracks_reflects_latest_only(session):
    asset, company = _asset_and_company(session)
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    assert confirmed_tracks(session, asset.id) == {Track.producer}

    # A later denial overrides the earlier confirmation for the same (company, track).
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_denied, validated_by="b")
    assert confirmed_tracks(session, asset.id) == set()


def test_confirmed_tracks_spans_companies_and_tracks(session):
    asset, company = _asset_and_company(session)
    other, _ = resolve_company(session, name="Global Foundry")
    session.commit()
    record_need_validation(session, asset, company_id=company.id, track=Track.producer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    record_need_validation(session, asset, company_id=other.id, track=Track.customer,
                           outcome=NeedOutcome.need_confirmed, validated_by="a")
    assert confirmed_tracks(session, asset.id) == {Track.producer, Track.customer}


# -- TRL axis ---------------------------------------------------------------
def test_trl_check_records_inventor_answer_and_latest_wins(session):
    asset, _ = _asset_and_company(session)
    record_trl_check(session, asset, trl_band="2-4",
                     evidence={"simulation_only": True}, recorded_by="inv")
    record_trl_check(session, asset, trl_band="6-9",
                     evidence={"prototype": True, "real_case_tested": True}, recorded_by="inv")
    latest = latest_trl_check(session, asset.id)
    assert latest.trl_band == "6-9" and latest.evidence["prototype"] is True


def test_config_reads_bands_high_low_deterministically():
    assert TRL.is_high("6-9") is True
    assert TRL.is_high("2-4") is False


def test_questionnaire_is_generated_but_not_answered():
    q = build_questionnaire(TRL)
    assert set(TRL.bands) == set(q.bands)
    ids = {question["id"] for question in q.questions}
    assert {"prototype", "real_case_tested", "simulation_only"} <= ids
    rendered = q.render()
    assert "inventor answers" in rendered.lower()


def test_validate_band_rejects_unknown_band():
    import pytest

    validate_band("6-9", TRL)  # ok
    with pytest.raises(ValueError, match="not one of"):
        validate_band("9-10", TRL)
