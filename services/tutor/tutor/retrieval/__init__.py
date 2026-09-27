from __future__ import annotations

from .corpus import Corpus, load_corpus
from .refs import (
    SourceRef,
    UnresolvedRef,
    cite_passage,
    cite_ref,
    parse_ref,
    passage_label,
    ref_label,
    resolve_ref,
)

__all__ = [
    "Corpus",
    "SourceRef",
    "UnresolvedRef",
    "cite_passage",
    "cite_ref",
    "load_corpus",
    "parse_ref",
    "passage_label",
    "ref_label",
    "resolve_ref",
]
