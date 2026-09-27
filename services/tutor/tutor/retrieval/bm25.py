"""Pure-Python BM25 indexing with stable, corpus-independent confidence.

Confidence is idf-weighted query coverage: the fraction of the query's unique
terms, weighted by their corpus rarity, that occur in a passage. Unlike a
result-relative score, it remains stable when the candidate set changes.
"""
from __future__ import annotations

import math
from collections import Counter


class BM25Index:
    K1 = 1.5
    B = 0.75

    def __init__(self, docs: list[list[str]]) -> None:
        self.docs = docs
        self._lengths = [len(doc) for doc in docs]
        self._average_length = sum(self._lengths) / len(self._lengths) if docs else 0.0
        self._term_frequencies = [Counter(doc) for doc in docs]
        self._document_frequency: Counter[str] = Counter()
        for terms in self._term_frequencies:
            self._document_frequency.update(terms.keys())

    def idf(self, term: str) -> float:
        n = len(self.docs)
        df = self._document_frequency.get(term, 0)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def score(self, query_terms: list[str], i: int) -> float:
        if i < 0 or i >= len(self.docs):
            raise IndexError(i)
        if not self.docs or not query_terms:
            return 0.0
        length = self._lengths[i]
        normaliser = 1.0 - self.B + self.B * length / self._average_length if self._average_length else 1.0
        frequencies = self._term_frequencies[i]
        return sum(
            self.idf(term)
            * frequency
            * (self.K1 + 1.0)
            / (frequency + self.K1 * normaliser)
            for term in sorted(set(query_terms))  # fixed order: float sums must not depend on hash seeds
            if (frequency := frequencies.get(term, 0))
        )

    def confidence(self, query_terms: list[str], i: int) -> float:
        unique = sorted(set(query_terms))
        if not unique:
            return 0.0
        denominator = sum(self.idf(term) for term in unique)
        if denominator == 0.0:
            return 0.0
        present = set(self.docs[i])
        value = sum(self.idf(term) for term in unique if term in present) / denominator
        return max(0.0, min(1.0, value))
