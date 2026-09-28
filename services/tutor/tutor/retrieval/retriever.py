from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import settings
from ..content import ContentPack
from ..contracts.content import Passage, ScoredPassage
from .bm25 import BM25Index
from .corpus import Corpus, load_corpus
from .refs import UnresolvedRef, resolve_ref
from .text import Normaliser, load_synonyms
from .vectors import VectorIndex, load_vectors, get_embedder

@dataclass(frozen=True)
class SearchFilters:
    doc_types: frozenset[str] | None = None
    attempt: str | None = None
    chapter: str | None = None
    node_ids: frozenset[str] | None = None


class Retriever(Protocol):
    def for_node(self, node_id: str) -> list[Passage]: ...
    def search(self, query: str, k: int = 5, filters: SearchFilters | None = None) -> list[ScoredPassage]: ...


class PackRetriever:
    def __init__(self, corpus: Corpus, normaliser: Normaliser) -> None:
        self.corpus = corpus
        self.normaliser = normaliser
        self._passages = list(corpus.by_id.values())
        self._index = BM25Index([normaliser.tokens(passage.text) for passage in self._passages])
        self._node_passages: dict[str, list[Passage]] = {}
        self._vector_index = load_vectors(corpus)

    def for_node(self, node_id: str) -> list[Passage]:
        if node_id not in self.corpus.pack.curriculum.by_id:
            raise KeyError(node_id)
        if node_id in self._node_passages:
            return list(self._node_passages[node_id])
        out: list[Passage] = []
        seen: set[str] = set()
        node = self.corpus.pack.curriculum.node(node_id)
        for ref in node.source_refs:
            try:
                passages = resolve_ref(ref, self.corpus)
            except UnresolvedRef:
                logging.warning("Unresolved source reference for node %s: %s", node_id, ref)
                continue
            for passage in passages:
                if passage.passage_id not in seen:
                    seen.add(passage.passage_id)
                    out.append(passage)
        self._node_passages[node_id] = out
        return list(out)

    def search(self, query: str, k: int = 5, filters: SearchFilters | None = None) -> list[ScoredPassage]:
        terms = self.normaliser.tokens(query)
        filters = filters or SearchFilters()
        allowed_ids: set[str] | None = None
        if filters.node_ids is not None:
            allowed_ids = {
                passage.passage_id
                for node_id in sorted(filters.node_ids)
                for passage in self.for_node(node_id)
            }

        # BM25 search
        bm25_scored: list[tuple[int, float, float]] = [] # (index, score, confidence)
        for i, passage in enumerate(self._passages):
            if allowed_ids is not None and passage.passage_id not in allowed_ids:
                continue
            if filters.doc_types is not None and passage.doc_type not in filters.doc_types:
                continue
            if filters.attempt is not None and passage.attempt != filters.attempt:
                continue
            if filters.chapter is not None and passage.chapter != filters.chapter:
                continue

            score = self._index.score(terms, i)
            conf = self._index.confidence(terms, i)
            bm25_scored.append((i, score, conf))

        # Hybrid search
        if settings.retrieval_mode == "hybrid" and self._vector_index:
            try:
                embedder = get_embedder(settings.embed_model or self._vector_index.model)
                embed_query = getattr(embedder, "embed_query", None)
                query_vec = embed_query(query) if embed_query else embedder.embed([query])[0]

                hybrid_scored: list[ScoredPassage] = []
                w = settings.hybrid_weight

                # Every passage passing filters is a candidate, even if BM25 score is 0
                # We need to map BM25 results back to indices
                bm25_map = {idx: (score, conf) for idx, score, conf in bm25_scored}

                for i, passage in enumerate(self._passages):
                    # Re-apply filters (since bm25_scored already filtered)
                    if allowed_ids is not None and passage.passage_id not in allowed_ids:
                        continue
                    if filters.doc_types is not None and passage.doc_type not in filters.doc_types:
                        continue
                    if filters.attempt is not None and passage.attempt != filters.attempt:
                        continue
                    if filters.chapter is not None and passage.chapter != filters.chapter:
                        continue

                    sim = self._vector_index.similarity(query_vec, passage.passage_id)
                    bm25_score, bm25_conf = bm25_map.get(i, (0.0, 0.0))

                    # score = w * similarity + (1 - w) * bm25_confidence
                    total_score = w * sim + (1 - w) * bm25_conf

                    if total_score > 0:
                        hybrid_scored.append(
                            ScoredPassage(
                                passage=passage,
                                score=total_score,
                                confidence=total_score, # confidence = score in hybrid
                            )
                        )

                if settings.hybrid_fusion == "rrf":
                    hybrid_scored = _rrf(hybrid_scored, bm25_map, self._passages, self._vector_index, query_vec)
                hybrid_scored.sort(key=lambda item: (-item.score, item.passage.passage_id))
                return hybrid_scored[: max(0, k)]

            except Exception as e:
                logging.warning("Hybrid search failed, falling back to BM25: %s", e)

        # Fallback or BM25 mode
        final_scored: list[ScoredPassage] = []
        for i, score, conf in bm25_scored:
            if score > 0.0:
                final_scored.append(
                    ScoredPassage(
                        passage=self._passages[i],
                        score=score,
                        confidence=conf,
                    )
                )
        final_scored.sort(key=lambda item: (-item.score, item.passage.passage_id))
        return final_scored[: max(0, k)]


def _rrf(candidates, bm25_map, passages, index, query_vec, k: int = 60):
    """Rank candidates by reciprocal rank fusion of the BM25 and vector rankings; keep the
    weighted blend as the confidence, so the out-of-scope threshold keeps its meaning."""
    index_of = {p.passage_id: i for i, p in enumerate(passages)}
    def ranks(key):
        ordered = sorted(candidates, key=lambda c: (-key(c), c.passage.passage_id))
        return {c.passage.passage_id: r for r, c in enumerate(ordered, start=1)}
    by_bm25 = ranks(lambda c: bm25_map.get(index_of[c.passage.passage_id], (0.0, 0.0))[0])
    by_vec = ranks(lambda c: index.similarity(query_vec, c.passage.passage_id))
    return [
        ScoredPassage(passage=c.passage, confidence=c.confidence,
                      score=1 / (k + by_bm25[c.passage.passage_id]) + 1 / (k + by_vec[c.passage.passage_id]))
        for c in candidates
    ]


_RETRIEVER_CACHE: dict[tuple[Path, str, str, str], PackRetriever] = {}


def get_retriever(pack: ContentPack) -> PackRetriever | None:
    corpus = load_corpus(pack)
    if corpus is None:
        return None
    normaliser = Normaliser(load_synonyms(pack))
    # Cache key now includes retrieval_mode
    key = (pack.root.resolve(), corpus.corpus_sha256, normaliser.sha256, settings.retrieval_mode)
    cached = _RETRIEVER_CACHE.get(key)
    if cached is not None:
        return cached
    retriever = PackRetriever(corpus, normaliser)
    _RETRIEVER_CACHE[key] = retriever
    return retriever
