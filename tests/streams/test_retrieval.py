"""Deterministic TF-IDF retriever."""

from __future__ import annotations

from dataclasses import dataclass

from forge.streams.retrieval import LexicalRetriever, tokenize


@dataclass
class Doc:
    id: str
    text: str


DOCS = [
    Doc("photonics", "photonic optical interconnect for edge computing accelerators"),
    Doc("hydrogen", "green hydrogen electrolyser for decarbonising industry"),
    Doc("ai", "artificial intelligence machine learning risk regulation"),
]


def retriever() -> LexicalRetriever:
    return LexicalRetriever(DOCS, lambda d: d.text)


def test_tokenize_drops_stopwords_and_short_tokens():
    assert tokenize("A photonic Interconnect for the edge") == [
        "photonic", "interconnect", "edge"
    ]


def test_query_ranks_most_relevant_first():
    hits = retriever().query("optical photonic interconnect", top_k=3)
    assert hits[0].doc.id == "photonics"
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_no_overlap_returns_nothing():
    assert retriever().query("submarine sandwich recipe") == []


def test_top_k_caps_results():
    hits = retriever().query("photonic hydrogen intelligence", top_k=1)
    assert len(hits) == 1


def test_ranking_is_deterministic():
    a = [(h.doc.id, round(h.score, 6)) for h in retriever().query("edge computing")]
    b = [(h.doc.id, round(h.score, 6)) for h in retriever().query("edge computing")]
    assert a == b
