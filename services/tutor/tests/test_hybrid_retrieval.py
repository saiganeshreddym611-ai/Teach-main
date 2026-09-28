from __future__ import annotations

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock

from tutor.config import settings
from tutor.retrieval import get_retriever
from tutor.retrieval.vectors import HashEmbedder, write_vectors, load_vectors, VectorIndex
from tutor.retrieval.retriever import PackRetriever, SearchFilters

class DictEmbedder:
    def __init__(self, mapping: dict[str, list[float]]):
        self.name = "dict-embedder"
        self.mapping = mapping

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.mapping.get(t, [0.0]*128) for t in texts]

@pytest.fixture
def fixture_115(tmp_path):
    # Simplified fixture_115 for testing
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    # Valid Pydantic values for Passage
    chunks = [
        {"passage_id": "p1", "text": "The quick brown fox", "doc_id": "d1", "doc_type": "standard", "attempt": "a", "chapter": "c", "locator": "l", "page": 1, "paper": "p", "section": "s", "sha256": "a" * 64, "supersedes": [], "version": "v"},
        {"passage_id": "p2", "text": "Jumped over the lazy dog", "doc_id": "d1", "doc_type": "standard", "attempt": "a", "chapter": "c", "locator": "l", "page": 1, "paper": "p", "section": "s", "sha256": "b" * 64, "supersedes": [], "version": "v"},
    ]

    (corpus_dir / "chunks.jsonl").write_text("\n".join(json.dumps(c) for c in chunks) + "\n", encoding="utf-8")
    (corpus_dir / "manifest.json").write_text(json.dumps({"corpus_sha256": "sha_115", "chunk_count": 2}), encoding="utf-8")

    # Create a dummy sources.json for load_sources()
    (corpus_dir / "sources.json").write_text(json.dumps([]), encoding="utf-8")

    # Mock a ContentPack
    pack = MagicMock()
    pack.root = tmp_path
    pack.corpus_dir = corpus_dir
    # sources_path must be a Path object that actually exists or behaves like one
    pack.sources_path = corpus_dir / "sources.json"
    pack.manifest.doc_codes = {}
    pack.curriculum.by_id = {}
    pack.curriculum.node = lambda id: MagicMock(source_refs=[])

    return pack

def test_hash_embedder_deterministic_unit_length():
    embedder = HashEmbedder()
    text = "The quick brown fox jumps over the lazy dog"
    vec1 = embedder.embed([text])[0]
    vec2 = embedder.embed([text])[0]

    assert vec1 == vec2
    norm = sum(x*x for x in vec1)**0.5
    assert norm == pytest.approx(1.0, abs=1e-6)

def test_write_and_load_vectors(fixture_115, tmp_path):
    from tutor.retrieval.corpus import load_corpus
    corpus = load_corpus(fixture_115)
    embedder = HashEmbedder()

    vectors = {pid: [0.1]*256 for pid in corpus.by_id}
    write_vectors(fixture_115, vectors, embedder, corpus)

    # Check files
    vectors_file = fixture_115.corpus_dir / "vectors.jsonl"
    assert vectors_file.is_file()

    manifest_file = fixture_115.corpus_dir / "vectors_manifest.json"
    manifest = json.loads(manifest_file.read_text())
    assert manifest["model"] == embedder.name
    assert manifest["corpus_sha256"] == corpus.corpus_sha256

    # Load back
    index = load_vectors(corpus)
    assert index is not None
    assert index.model == embedder.name

def test_stale_vectors_ignored(fixture_115):
    from tutor.retrieval.corpus import load_corpus
    corpus = load_corpus(fixture_115)
    embedder = HashEmbedder()
    vectors = {pid: [0.1]*256 for pid in corpus.by_id}
    write_vectors(fixture_115, vectors, embedder, corpus)

    # Corrupt manifest sha256
    manifest_file = fixture_115.corpus_dir / "vectors_manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["corpus_sha256"] = "wrong_sha"
    manifest_file.write_text(json.dumps(manifest))

    index = load_vectors(corpus)
    assert index is None

def test_hybrid_finds_zero_overlap_match(fixture_115):
    from tutor.retrieval.corpus import load_corpus
    from tutor.retrieval.text import Normaliser
    corpus = load_corpus(fixture_115)
    normaliser = Normaliser({})

    # Use a DictEmbedder to force matches
    query = "find me"
    passage_text = "The quick brown fox" # p1
    vec_query = [1.0] * 128
    vec_p1 = [1.0] * 128
    vec_p2 = [0.0] * 128

    embedder = DictEmbedder({query: vec_query, passage_text: vec_p1, "Jumped over the lazy dog": vec_p2})

    # We need to inject the VectorIndex
    retriever = PackRetriever(corpus, normaliser)
    retriever._vector_index = VectorIndex("dict", {
        "p1": vec_p1,
        "p2": vec_p2
    })

    # Monkeypatch get_embedder to return our DictEmbedder
    import tutor.retrieval.vectors as vectors_mod
    from tutor.retrieval import retriever as retriever_mod

    original_get_embedder = vectors_mod.get_embedder
    vectors_mod.get_embedder = lambda model: embedder

    # Since retriever.py does 'from .vectors import get_embedder',
    # it has its own reference to the function. We must patch that too.
    original_retriever_get_embedder = retriever_mod.get_embedder
    retriever_mod.get_embedder = lambda model: embedder

    settings.retrieval_mode = "hybrid"
    # Important: set embed_model so get_embedder(settings.embed_model or self._vector_index.model)
    # doesn't fall back to "dict" if we want a specific embedder, though here it should be fine.
    # The real issue is that get_embedder is called with a model name.
    # Let's make sure the vector index model matches our DictEmbedder's name.
    retriever._vector_index.model = embedder.name

    results = retriever.search(query, k=1)
    assert len(results) > 0
    assert results[0].passage.passage_id == "p1"

    settings.retrieval_mode = "bm25"
    results_bm25 = retriever.search(query, k=1)
    assert len(results_bm25) == 0

    vectors_mod.get_embedder = original_get_embedder
    settings.retrieval_mode = "bm25"

def test_hybrid_deterministic_and_ids_only(fixture_115):
    from tutor.retrieval.corpus import load_corpus
    from tutor.retrieval.text import Normaliser
    corpus = load_corpus(fixture_115)
    normaliser = Normaliser({})
    retriever = PackRetriever(corpus, normaliser)

    # Mock vector index
    retriever._vector_index = VectorIndex("mock", {"p1": [0.1]*128, "p2": [0.2]*128})

    from tutor.retrieval.vectors import get_embedder
    import tutor.retrieval.vectors as vectors_mod
    original_get_embedder = vectors_mod.get_embedder
    vectors_mod.get_embedder = lambda model: DictEmbedder({"test": [0.1]*128})

    settings.retrieval_mode = "hybrid"
    res1 = retriever.search("test", k=5)
    res2 = retriever.search("test", k=5)

    assert res1 == res2
    for r in res1:
        assert r.passage.passage_id in corpus.by_id

    vectors_mod.get_embedder = original_get_embedder
    settings.retrieval_mode = "bm25"

def test_bm25_mode_unchanged(fixture_115):
    from tutor.retrieval.corpus import load_corpus
    from tutor.retrieval.text import Normaliser
    corpus = load_corpus(fixture_115)
    normaliser = Normaliser({})

    retriever = PackRetriever(corpus, normaliser)
    # With vectors loaded
    retriever._vector_index = VectorIndex("mock", {"p1": [0.1]*128, "p2": [0.2]*128})

    settings.retrieval_mode = "bm25"
    results = retriever.search("quick brown", k=5)

    # Now without vectors
    retriever._vector_index = None
    results_no_vec = retriever.search("quick brown", k=5)

    assert results == results_no_vec

def test_embed_failure_falls_back(fixture_115):
    from tutor.retrieval.corpus import load_corpus
    from tutor.retrieval.text import Normaliser
    corpus = load_corpus(fixture_115)
    normaliser = Normaliser({})

    retriever = PackRetriever(corpus, normaliser)
    retriever._vector_index = VectorIndex("mock", {"p1": [0.1]*128, "p2": [0.2]*128})

    # Embedder that raises
    class FailingEmbedder:
        name = "fail"
        def embed(self, texts): raise Exception("Ollama down")

    from tutor.retrieval.vectors import get_embedder
    import tutor.retrieval.vectors as vectors_mod
    original_get_embedder = vectors_mod.get_embedder
    vectors_mod.get_embedder = lambda model: FailingEmbedder()

    settings.retrieval_mode = "hybrid"
    # Should not crash, should return BM25 results (which are empty for "fail")
    results = retriever.search("fail", k=5)
    assert isinstance(results, list)

    vectors_mod.get_embedder = original_get_embedder
    settings.retrieval_mode = "bm25"
