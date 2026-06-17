"""Pluggable retrieval for the S3 stream.

The default ``LexicalRetriever`` is a deterministic TF-IDF cosine scorer with no
third-party dependencies — so the stream is testable offline and reproducible.
An embedding-backed retriever can implement the same ``Retriever`` protocol and
be swapped in (like the LLM provider) without touching the stream.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, Protocol

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "is",
    "are", "by", "at", "as", "that", "this", "it", "its", "be", "from", "into",
}


def tokenize(text: str) -> list[str]:
    return [
        tok
        for tok in re.findall(r"[a-z0-9]+", text.lower())
        if len(tok) > 1 and tok not in _STOPWORDS
    ]


@dataclass
class ScoredDoc:
    doc: object
    score: float


class Retriever(Protocol):
    def query(self, text: str, *, top_k: int = 5) -> list[ScoredDoc]: ...


class LexicalRetriever:
    """TF-IDF cosine retriever. ``text_of`` extracts a doc's searchable text."""

    def __init__(self, docs, text_of: Callable[[object], str]) -> None:
        self._docs = list(docs)
        n = len(self._docs)

        term_freqs: list[dict[str, int]] = []
        doc_freq: dict[str, int] = {}
        for doc in self._docs:
            counts: dict[str, int] = {}
            for tok in tokenize(text_of(doc)):
                counts[tok] = counts.get(tok, 0) + 1
            term_freqs.append(counts)
            for tok in counts:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        # Smoothed IDF (always positive, so a term in every doc still contributes).
        self._idf = {t: math.log((n + 1) / (df + 1)) + 1.0 for t, df in doc_freq.items()}
        self._vectors = [self._weight(counts) for counts in term_freqs]
        self._norms = [self._norm(vec) for vec in self._vectors]

    def _weight(self, counts: dict[str, int]) -> dict[str, float]:
        return {t: c * self._idf.get(t, 0.0) for t, c in counts.items()}

    @staticmethod
    def _norm(vec: dict[str, float]) -> float:
        return math.sqrt(sum(w * w for w in vec.values())) or 1.0

    def query(self, text: str, *, top_k: int = 5) -> list[ScoredDoc]:
        q_counts: dict[str, int] = {}
        for tok in tokenize(text):
            q_counts[tok] = q_counts.get(tok, 0) + 1
        q_vec = self._weight(q_counts)
        q_norm = self._norm(q_vec)

        scored: list[ScoredDoc] = []
        for doc, vec, norm in zip(self._docs, self._vectors, self._norms):
            dot = sum(w * vec.get(t, 0.0) for t, w in q_vec.items())
            score = dot / (q_norm * norm)
            if score > 0:
                scored.append(ScoredDoc(doc=doc, score=score))

        # Deterministic ordering: score desc, then a stable doc key.
        scored.sort(key=lambda s: (-s.score, str(getattr(s.doc, "id", ""))))
        return scored[:top_k]
