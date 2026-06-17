"""S3 — roadmaps/standards cross-referencing (curated corpus, semantic retrieval).

Answers: "is there industrial/regulatory pull?" by retrieving the curated corpus
of roadmaps, standards, and regulations most relevant to the asset's problem
space, and normalising the hits into evidence records. Retrieval is via a
pluggable ``Retriever`` (default: deterministic TF-IDF), so this is reproducible
and offline-testable. The corpus is public/curated data (rule 4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..db.models import Licence
from ..enrichment.profiling import AssetProfile
from .analysis import clamp_unit
from .base import EvidenceRecord, SourceSpec, StreamResult, SubSignal
from .retrieval import LexicalRetriever, Retriever

STREAM = "S3_roadmaps"
SOURCE_TYPE = "s3_corpus"


@dataclass
class CorpusDoc:
    id: str
    title: str
    source: str
    doc_type: str  # roadmap | standard | regulation
    text: str
    url: str | None = None


def load_corpus(path: str) -> list[CorpusDoc]:
    """Load a JSONL corpus file into CorpusDocs."""
    docs: list[CorpusDoc] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            docs.append(
                CorpusDoc(
                    id=raw["id"],
                    title=raw.get("title", raw["id"]),
                    source=raw.get("source", ""),
                    doc_type=raw.get("doc_type", "document"),
                    text=raw.get("text", ""),
                    url=raw.get("url"),
                )
            )
    return docs


def corpus_text(doc: CorpusDoc) -> str:
    return f"{doc.title} {doc.source} {doc.text}"


class S3RoadmapsStream:
    """Retrieve relevant roadmaps/standards for a profile and emit evidence."""

    def __init__(self, retriever: Retriever, *, config: dict) -> None:
        self.retriever = retriever
        self.top_k = int(config.get("top_k", 5))
        self.min_score = float(config.get("min_score", 0.0))

    def _query_text(self, profile: AssetProfile) -> str:
        parts = list(profile.query_terms) + [profile.problem.value, profile.solution.value]
        return " ".join(parts)

    def run(self, profile: AssetProfile) -> StreamResult:
        result = StreamResult(stream=STREAM)
        hits = [
            h
            for h in self.retriever.query(self._query_text(profile), top_k=self.top_k)
            if h.score >= self.min_score
        ]
        if not hits:
            return result

        evidence = [
            EvidenceRecord(
                stream=STREAM,
                match_strength=clamp_unit(h.score),
                snippet=f"{h.doc.doc_type}: {h.doc.title} ({h.doc.source})",
                link=h.doc.url,
                source=SourceSpec(SOURCE_TYPE, Licence.public, h.doc.id),
            )
            for h in hits
        ]
        result.sub_signals.append(
            SubSignal(
                name="industrial_regulatory_pull",
                value=float(len(hits)),
                detail=f"{len(hits)} roadmap/standard match(es): "
                + "; ".join(h.doc.title for h in hits),
                evidence=evidence,
            )
        )
        return result


def build_s3_stream(streams_config) -> S3RoadmapsStream:
    """Build an S3 stream from streams config (loads corpus + builds retriever)."""
    section = streams_config.section("s3_roadmaps")
    docs = load_corpus(section["corpus_path"])
    retriever = LexicalRetriever(docs, corpus_text)
    return S3RoadmapsStream(retriever, config=section)
