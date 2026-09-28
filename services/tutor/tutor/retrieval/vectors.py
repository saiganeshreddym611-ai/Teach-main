from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Protocol, TypedDict

from ollama import Client
from ..config import settings
from .corpus import Corpus, load_corpus

class VectorManifest(TypedDict):
    model: str
    dim: int
    corpus_sha256: str
    count: int

class Embedder(Protocol):
    name: str
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class OllamaEmbedder:
    def __init__(self, model: str):
        self.name = model
        self.client = Client(host=settings.ollama_host)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            responses = self.client.embed(model=self.name, input=texts)
            return responses["embeddings"]
        except Exception as e:
            logging.warning("Ollama embed error (%s): %s", self.name, e)
            raise

class HashEmbedder:
    def __init__(self):
        self.name = "hash-256"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            # Deterministic hashed bag of words: 256 dims
            vec = [0.0] * 256
            for word in text.split():
                idx = sum(ord(c) for c in word) % 256
                vec[idx] += 1.0
            
            # Unit length
            norm = math.sqrt(sum(x*x for x in vec))
            if norm > 0:
                vec = [x/norm for x in vec]
            vectors.append(vec)
        return vectors

def get_embedder(model: str) -> Embedder:
    if model == "hash-256":
        return HashEmbedder()
    return OllamaEmbedder(model)

class VectorIndex:
    def __init__(self, model: str, vectors: dict[str, list[float]]):
        self.model = model
        self.vectors = vectors

    def similarity(self, query_vector: list[float], passage_id: str) -> float:
        vec = self.vectors.get(passage_id)
        if vec is None:
            return 0.0
        
        # Cosine similarity of unit vectors is just dot product
        dot = sum(q * v for q, v in zip(query_vector, vec))
        return max(0.0, min(1.0, dot))

def build_vectors(corpus: Corpus, embedder: Embedder, batch: int = 16) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    passages = list(corpus.by_id.values())
    
    for i in range(0, len(passages), batch):
        batch_passages = passages[i : i + batch]
        texts = [p.text for p in batch_passages]
        embeddings = embedder.embed(texts)
        for p, v in zip(batch_passages, embeddings):
            vectors[p.passage_id] = v
            
    return vectors

def write_vectors(pack, vectors: dict[str, list[float]], embedder: Embedder, corpus: Corpus) -> None:
    corpus_dir = pack.corpus_dir
    vectors_file = corpus_dir / "vectors.jsonl"
    manifest_file = corpus_dir / "vectors_manifest.json"
    
    # Sorted by passage_id
    sorted_ids = sorted(vectors.keys())
    
    with open(vectors_file, "w", encoding="utf-8", newline="\n") as f:
        for pid in sorted_ids:
            vec = vectors[pid]
            # Round to 6 decimals
            rounded_vec = [round(x, 6) for x in vec]
            line = json.dumps({"passage_id": pid, "vector": rounded_vec}, ensure_ascii=False)
            f.write(line + "\n")
            
    # Manifest
    manifest: VectorManifest = {
        "model": embedder.name,
        "dim": len(next(iter(vectors.values()))),
        "corpus_sha256": corpus.corpus_sha256,
        "count": len(vectors)
    }
    with open(manifest_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False)
        f.write("\n")

def load_vectors(corpus: Corpus) -> VectorIndex | None:
    corpus_dir = corpus.pack.corpus_dir
    vectors_file = corpus_dir / "vectors.jsonl"
    manifest_file = corpus_dir / "vectors_manifest.json"
    
    if not vectors_file.is_file() or not manifest_file.is_file():
        logging.warning("Vector files missing in %s", corpus_dir)
        return None
        
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest: VectorManifest = json.load(f)
            
        if manifest["corpus_sha256"] != corpus.corpus_sha256:
            logging.warning("Stale vectors: manifest sha256 %s != corpus %s", manifest["corpus_sha256"], corpus.corpus_sha256)
            return None
            
        vectors: dict[str, list[float]] = {}
        with open(vectors_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                data = json.loads(line)
                vectors[data["passage_id"]] = data["vector"]
                
        if len(vectors) != manifest["count"]:
            logging.warning("Vector count mismatch: manifest %d, loaded %d", manifest["count"], len(vectors))
            return None
            
        # Check all passages in corpus have a vector
        for pid in corpus.by_id:
            if pid not in vectors:
                logging.warning("Passage %s missing vector", pid)
                return None
                
        return VectorIndex(manifest["model"], vectors)
        
    except Exception as e:
        logging.warning("Error loading vectors: %s", e)
        return None
