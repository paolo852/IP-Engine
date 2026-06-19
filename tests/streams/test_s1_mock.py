"""E5: the synthetic S1 funding mock — default, deterministic, licence-separated."""

from __future__ import annotations

from types import SimpleNamespace

from forge.db.models import Licence
from forge.streams.s1_funding import MockS1Client, S1FundingStream

YEARS = [2023, 2024, 2025]


def test_mock_is_deterministic_and_synthetic():
    c = MockS1Client()
    assert c.licence is Licence.synthetic and c.source_type == "mock:funding"
    a = c.search_funding("optical interconnect market", years=YEARS)
    b = c.search_funding("optical interconnect market", years=YEARS)
    assert a.total_amount_eur == b.total_amount_eur and a.round_count == b.round_count
    other = c.search_funding("battery materials characterisation", years=YEARS)
    assert (a.total_amount_eur, a.round_count) != (other.total_amount_eur, other.round_count)
    assert a.total_amount_eur > 0


def test_stream_emits_synthetic_provenance_with_mock():
    stream = S1FundingStream(MockS1Client(), config={})
    profile = SimpleNamespace(query_terms=["co-packaged optics", "silicon photonics"])
    result = stream.run(profile, as_of_year=2025)

    assert result.sub_signals  # funding momentum present
    evidence = [e for s in result.sub_signals for e in s.evidence]
    assert evidence
    for e in evidence:
        assert e.source.licence is Licence.synthetic
        assert e.source.source_type == "mock:funding"  # never licensed_dealroom


def test_build_stream_clients_defaults_to_mock(monkeypatch):
    from forge.seed import build_stream_clients
    from forge.streams.s1_funding import DealroomS1Client

    monkeypatch.delenv("FORGE_DEALROOM_API_KEY", raising=False)
    monkeypatch.delenv("FORGE_EPO_OPS_KEY", raising=False)
    _, s1 = build_stream_clients()
    assert isinstance(s1, MockS1Client)

    monkeypatch.setenv("FORGE_DEALROOM_API_KEY", "x")
    _, s1_keyed = build_stream_clients()
    assert isinstance(s1_keyed, DealroomS1Client)


def test_seed_assets_get_funding_evidence_from_mock(session):
    from datetime import date

    from forge.db.models import Asset
    from forge.repository import get_evidence
    from forge.seed import seed_demo

    seed_demo(session, as_of=date(2026, 6, 18))
    asset = session.query(Asset).first()
    streams = {e.stream for e in get_evidence(session, asset.id)}
    assert "S1_funding" in streams  # S1 now contributes by default (mock)
