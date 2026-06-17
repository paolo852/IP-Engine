"""S3 roadmaps/standards stream: retrieval -> evidence."""

from __future__ import annotations

from forge.config import load_streams_config
from forge.streams.retrieval import LexicalRetriever
from forge.streams.s3_roadmaps import (
    CorpusDoc,
    S3RoadmapsStream,
    build_s3_stream,
    corpus_text,
    load_corpus,
)

from .fakes import profile

CORPUS = [
    CorpusDoc("photonics", "Photonics Roadmap", "Photonics21", "roadmap",
              "photonic optical interconnect for edge computing accelerators",
              url="https://example.org/p"),
    CorpusDoc("hydrogen", "Hydrogen Strategy", "EC", "roadmap",
              "green hydrogen electrolyser for industry"),
]


def stream(**cfg) -> S3RoadmapsStream:
    base = {"top_k": 5, "min_score": 0.0}
    base.update(cfg)
    return S3RoadmapsStream(LexicalRetriever(CORPUS, corpus_text), config=base)


def test_relevant_roadmap_becomes_a_pull_signal():
    p = profile(
        ["optical interconnect"],
        problem="energy per bit in chip interconnects",
        solution="a photonic edge computing interconnect",
    )
    result = stream().run(p)
    sig = result.signal("industrial_regulatory_pull")
    assert sig is not None
    # The photonics roadmap is the top (and only relevant) hit.
    assert sig.evidence[0].source.locator == "photonics"
    assert sig.evidence[0].source.licence.value == "public"
    assert "roadmap: Photonics Roadmap" in sig.evidence[0].snippet
    assert all(0.0 <= e.match_strength <= 1.0 for e in sig.evidence)


def test_min_score_filters_weak_matches():
    p = profile([], problem="photonic interconnect", solution="optical edge computing")
    # An impossibly high threshold removes everything.
    assert stream(min_score=1.01).run(p).sub_signals == []


def test_irrelevant_profile_yields_no_pull():
    p = profile([], problem="a wooden chair", solution="four legs and a seat")
    assert stream().run(p).sub_signals == []


def test_load_corpus_and_build_from_config():
    docs = load_corpus("data/s3_corpus.jsonl")
    assert any(d.id == "eu-photonics-roadmap" for d in docs)

    s3 = build_s3_stream(load_streams_config("config/streams.yaml"))
    result = s3.run(
        profile(
            ["photonic interconnect", "edge AI"],
            problem="inter-chip energy per bit",
            solution="micro-ring modulator optical interconnect",
        )
    )
    titles = result.signal("industrial_regulatory_pull").detail
    assert "Photonics Roadmap" in titles  # the curated corpus's photonics entry
