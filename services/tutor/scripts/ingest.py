"""Build the generated corpus for a content pack."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tutor.content import PACKS_DIR, ContentPackError, load_pack, load_sources
from tutor.ingest import IngestError, build_corpus, write_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, help="Content pack ID")
    parser.add_argument("--packs-dir", type=Path, default=PACKS_DIR, help="Directory containing packs")
    parser.add_argument("--no-hash-check", action="store_true", help="Skip source sha256 verification")
    parser.add_argument("--embed", help="Model to embed the corpus with")
    args = parser.parse_args(argv)

    try:
        pack = load_pack(args.pack, packs_dir=args.packs_dir)
        passages, manifest, warnings = build_corpus(pack, check_hashes=not args.no_hash_check)
        write_corpus(pack, passages, manifest)

        if args.embed:
            from tutor.retrieval.vectors import build_vectors, write_vectors, get_embedder
            from tutor.retrieval import load_corpus
            corpus = load_corpus(pack)
            if corpus:
                embedder = get_embedder(args.embed)
                vectors = build_vectors(corpus, embedder)
                write_vectors(pack, vectors, embedder, corpus)
                print(f"Embedded corpus with {args.embed}")
    except (IngestError, ContentPackError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    source_counts = {doc.doc_id: 0 for doc in load_sources(pack)}
    for passage in passages:
        source_counts[passage.doc_id] = source_counts.get(passage.doc_id, 0) + 1
    for doc_id, count in source_counts.items():
        print(f"{doc_id}: {count} passages")
    for warning in warnings:
        print(f"Warning: {warning}")
    print(f"chunk_count: {manifest.chunk_count}")
    print(f"corpus_sha256: {manifest.corpus_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
