"""T11: the need-hypothesis generator — matching, track, strength, falsifiability."""

from __future__ import annotations

import uuid

from forge.config import load_needs_config
from forge.db.models import Company, Relationship, RelationshipType, Strength, Track
from forge.matching import generate
from forge.matching.need_hypothesis import strength_of

CFG = load_needs_config("config/needs.yaml")


def _company(name: str, *, topics=(), strength=Strength.medium) -> Company:
    rels = [
        Relationship(
            type=RelationshipType.collaborative_project,
            topic=t,
            strength=strength,
            source_layer=0,
            source_ref=f"cordis:project:{i}",
        )
        for i, t in enumerate(topics)
    ]
    return Company(id=uuid.uuid4(), name=name, relationships=rels)


PRODUCER_APP = {
    "application": "co-packaged optics",
    "end_customer": "data centre operators",
    "use_case": "rack-scale interconnect",
    "industry_terms": ["photonics", "silicon photonics", "optical interconnect"],
}
CUSTOMER_APP = {
    "application": "quality control in semiconductor fabs",
    "end_customer": "semiconductor foundries",
    "use_case": "inline wafer inspection",
    "industry_terms": ["nv magnetometry"],
}


def test_strength_converges_from_tie_terms_and_signal():
    assert strength_of(Strength.medium, 1, market_signal=False, cfg=CFG) is Strength.medium
    assert strength_of(Strength.medium, 2, market_signal=False, cfg=CFG) is Strength.strong
    assert strength_of(Strength.weak, 1, market_signal=True, cfg=CFG) is Strength.medium
    assert strength_of(Strength.strong, 9, market_signal=True, cfg=CFG) is Strength.strong  # clamp


def test_producer_track_for_an_adjacent_maker():
    comp = _company("Aurora Photonics GmbH", topics=["PHOTON-EDGE"])
    [d] = generate(
        applications=[PRODUCER_APP],
        technology_summary="A silicon photonics interconnect",
        companies=[comp],
        market_signal=False,
        cfg=CFG,
    )
    assert d.track is Track.producer
    assert "produce or license" in d.hypothesised_need
    assert d.hypothesised_need.startswith("Hypothesis (unvalidated")
    assert d.strength is Strength.medium  # base medium, 1 shared term, no signal
    # grounded: the graph tie and the shared term are recorded as evidence.
    kinds = {e["kind"] for e in d.evidence}
    assert "graph" in kinds and "shared_terms" in kinds
    assert any(e.get("ref") == "cordis:project:0" for e in d.evidence)


def test_customer_track_for_a_firm_with_the_problem():
    comp = _company("Global Semiconductor Foundry", topics=["wafer inspection"])
    [d] = generate(
        applications=[CUSTOMER_APP],
        technology_summary=None,
        companies=[comp],
        market_signal=True,
        cfg=CFG,
    )
    assert d.track is Track.customer
    assert "may need a solution" in d.hypothesised_need
    assert d.strength is Strength.strong  # >=2 shared terms + market signal


def test_market_signal_is_recorded_as_evidence():
    comp = _company("Aurora Photonics GmbH", topics=["PHOTON-EDGE"])
    [d] = generate(
        applications=[PRODUCER_APP], technology_summary=None,
        companies=[comp], market_signal=True, cfg=CFG,
    )
    assert any(e["kind"] == "market_signal" for e in d.evidence)


def test_unrelated_company_yields_no_hypothesis():
    comp = _company("Green Valley Foods Ltd", topics=["organic agriculture"])
    assert generate(
        applications=[PRODUCER_APP], technology_summary=None,
        companies=[comp], market_signal=False, cfg=CFG,
    ) == []


def test_hypothesis_never_claims_a_known_need():
    comp = _company("Aurora Photonics GmbH", topics=["PHOTON-EDGE"])
    [d] = generate(
        applications=[PRODUCER_APP], technology_summary=None,
        companies=[comp], market_signal=False, cfg=CFG,
    )
    text = d.hypothesised_need.lower()
    assert "unvalidated" in text and "falsifiable" in text
    assert "not a confirmed need" in text
