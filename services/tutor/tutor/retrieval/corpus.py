from __future__ import annotations

import json
from pathlib import Path

from ..content import ContentPack, load_sources
from ..contracts.content import Passage, SourceDoc


class Corpus:
    def __init__(
        self, pack: ContentPack, passages: list[Passage], sources: list[SourceDoc], corpus_sha256: str
    ) -> None:
        self.pack = pack
        self.corpus_sha256 = corpus_sha256
        self.by_id = {passage.passage_id: passage for passage in passages}
        self.docs = {source.doc_id: source for source in sources}
        self.order: dict[str, list[str]] = {}
        for passage in passages:
            self.order.setdefault(passage.doc_id, []).append(passage.passage_id)

    def passage(self, passage_id: str) -> Passage:
        return self.by_id[passage_id]

    def doc(self, doc_id: str) -> SourceDoc:
        return self.docs[doc_id]

    def doc_for_code(self, doc_code: str) -> SourceDoc | None:
        doc_id = self.pack.manifest.doc_codes.get(doc_code)
        if doc_id is not None and doc_id in self.docs:
            return self.docs[doc_id]
        matches = [doc for doc in self.docs.values() if doc.doc_code == doc_code]
        return matches[0] if len(matches) == 1 else None


def load_corpus(pack: ContentPack) -> Corpus | None:
    chunks_path = pack.corpus_dir / "chunks.jsonl"
    manifest_path = pack.corpus_dir / "manifest.json"
    if not chunks_path.is_file() or not manifest_path.is_file():
        return None
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus_sha256 = str(raw_manifest["corpus_sha256"])
    key = (pack.root.resolve(), corpus_sha256)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    passages = [
        Passage.model_validate(json.loads(line))
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = Corpus(pack, passages, load_sources(pack), corpus_sha256)
    _CACHE.clear()
    _CACHE[key] = corpus
    return corpus


_CACHE: dict[tuple[Path, str], Corpus] = {}
