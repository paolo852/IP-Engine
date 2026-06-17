"""S3 evidence persists into the shared store with public provenance."""

from __future__ import annotations

from forge.config import load_streams_config
from forge.repository import get_evidence, save_asset, save_stream_result
from forge.streams.s3_roadmaps import build_s3_stream

from ..synthetic.assets import synthetic_patent_bundle
from .fakes import profile


def test_s3_evidence_round_trips(session):
    asset = save_asset(session, synthetic_patent_bundle())
    s3 = build_s3_stream(load_streams_config("config/streams.yaml"))
    result = s3.run(
        profile(
            ["photonic interconnect"],
            problem="inter-chip energy per bit",
            solution="micro-ring modulator optical interconnect for edge computing",
        )
    )

    save_stream_result(session, asset, result)
    session.expunge_all()

    rows = get_evidence(session, asset.id, stream="S3_roadmaps")
    assert rows, "expected at least one roadmap evidence row"
    assert all(r.source.source_type == "s3_corpus" for r in rows)
    assert all(r.source.licence.value == "public" for r in rows)
    assert any("Photonics Roadmap" in r.snippet for r in rows)
