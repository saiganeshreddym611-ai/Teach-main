"""Source-document readers and deterministic corpus builders."""
from __future__ import annotations

from .pipeline import IngestError, SPLITTERS, build_corpus, write_corpus

__all__ = ["build_corpus", "write_corpus", "IngestError", "SPLITTERS"]
