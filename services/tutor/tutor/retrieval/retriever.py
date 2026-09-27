from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..content import ContentPack
from ..contracts.content import Passage, ScoredPassage
from .bm25 import BM25Index
from .corpus import Corpus, load_corpus
from .refs import UnresolvedRef, resolve_ref
from .text import Normaliser, load_synonyms


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
        scored: list[ScoredPassage] = []
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
            if score > 0.0:
                scored.append(
                    ScoredPassage(
                        passage=passage,
                        score=score,
                        confidence=self._index.confidence(terms, i),
                    )
                )
        scored.sort(key=lambda item: (-item.score, item.passage.passage_id))
        return scored[: max(0, k)]


_RETRIEVER_CACHE: dict[tuple[Path, str, str], PackRetriever] = {}


def get_retriever(pack: ContentPack) -> PackRetriever | None:
    corpus = load_corpus(pack)
    if corpus is None:
        return None
    normaliser = Normaliser(load_synonyms(pack))
    key = (pack.root.resolve(), corpus.corpus_sha256, normaliser.sha256)
    cached = _RETRIEVER_CACHE.get(key)
    if cached is not None:
        return cached
    retriever = PackRetriever(corpus, normaliser)
    _RETRIEVER_CACHE[key] = retriever
    return retriever
