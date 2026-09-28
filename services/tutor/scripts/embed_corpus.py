from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tutor.content import load_pack
from tutor.retrieval import load_corpus
from tutor.retrieval.vectors import build_vectors, write_vectors, get_embedder

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed a content pack corpus")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--packs-dir", type=Path)
    args = parser.parse_args(argv)

    pack = load_pack(args.pack, packs_dir=args.packs_dir)
    corpus = load_corpus(pack)
    if corpus is None:
        print(f"Error: pack {args.pack} has no corpus", file=sys.stderr)
        return 1

    embedder = get_embedder(args.model)
    print(f"Embedding {args.pack} with {args.model}...")
    vectors = build_vectors(corpus, embedder)
    write_vectors(pack, vectors, embedder, corpus)
    print("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
