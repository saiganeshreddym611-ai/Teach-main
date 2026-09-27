"""Deterministic source-to-corpus pipeline."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..content import ContentPack, load_sources
from ..contracts.content import CorpusManifest, DocType, Passage, SourceDoc
from .errors import IngestError
from .qa import split_qa
from .reader import read_source
from .standard import split_amendment, split_standard
from .study_material import split_study_material


@dataclass(frozen=True)
class SplitContext:
    paper: str
    attempt: str
    warnings: list[str] = field(default_factory=list, compare=False, repr=False)


Splitter = Callable[[SourceDoc, str, SplitContext], list[Passage]]

SPLITTERS: dict[DocType, Splitter] = {
    "standard": split_standard,
    "study_material": split_study_material,
    "rtp": split_qa,
    "mtp": split_qa,
    "past_paper": split_qa,
    "amendment": split_amendment,
}


def _chunks_bytes(passages: list[Passage]) -> bytes:
    return "".join(
        json.dumps(
            passage.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
        for passage in passages
    ).encode("utf-8")


def build_corpus(
    pack: ContentPack, *, check_hashes: bool = True
) -> tuple[list[Passage], CorpusManifest, list[str]]:
    passages: list[Passage] = []
    warnings: list[str] = []
    built_from: dict[str, str] = {}
    sources = load_sources(pack)
    context = SplitContext(
        paper=pack.manifest.paper,
        attempt=pack.manifest.attempt,
        warnings=warnings,
    )

    for doc in sources:
        path = pack.root / doc.path
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raise IngestError(f"{path}: {exc}") from exc
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        built_from[doc.doc_id] = raw_hash
        if not doc.sha256:
            warnings.append(f"{doc.doc_id}: sources.json has no sha256; actual sha256 is {raw_hash}.")
        elif check_hashes and doc.sha256 != raw_hash:
            raise IngestError(
                f"{path}: sha256 mismatch for {doc.doc_id}; update sources.json to match the source file."
            )
        text = read_source(path)
        splitter = SPLITTERS.get(doc.doc_type)
        if splitter is None:
            raise IngestError(f"{doc.doc_id}: no splitter for document type '{doc.doc_type}'")
        doc_passages = splitter(doc, text, context)
        passages.extend(doc_passages)
        if doc.doc_code not in pack.manifest.doc_codes:
            warnings.append(
                f"{doc.doc_id}: doc_code '{doc.doc_code}' is missing from manifest.doc_codes."
            )

    counts = Counter(passage.passage_id for passage in passages)
    duplicates = sorted(passage_id for passage_id, count in counts.items() if count > 1)
    if duplicates:
        raise IngestError(f"Duplicate passage_ids: {', '.join(duplicates)}")

    chunks = _chunks_bytes(passages)
    manifest = CorpusManifest(
        built_from=built_from,
        chunk_count=len(passages),
        corpus_sha256=hashlib.sha256(chunks).hexdigest(),
    )
    return passages, manifest, warnings


def write_corpus(pack: ContentPack, passages: list[Passage], manifest: CorpusManifest) -> None:
    chunks = _chunks_bytes(passages)
    manifest.corpus_sha256 = hashlib.sha256(chunks).hexdigest()
    manifest.chunk_count = len(passages)
    pack.corpus_dir.mkdir(parents=True, exist_ok=True)
    (pack.corpus_dir / "chunks.jsonl").write_bytes(chunks)
    manifest_bytes = (
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    (pack.corpus_dir / "manifest.json").write_bytes(manifest_bytes)
