from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tutor.content import load_pack
from tutor.retrieval.corpus import load_corpus
from tutor.retrieval.refs import UnresolvedRef, resolve_ref


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    args = parser.parse_args(argv)
    pack = load_pack(args.pack, packs_dir=args.packs_dir)
    corpus = load_corpus(pack)
    if corpus is None:
        print(f"No corpus for {args.pack}: run scripts/ingest.py first")
        return 2
    failures: list[str] = []
    count = 0
    for node in pack.curriculum.tree.nodes:
        for ref in node.source_refs:
            count += 1
            try:
                resolve_ref(ref, corpus)
            except UnresolvedRef as exc:
                failures.append(f"{node.id}  {ref}  {exc.reason}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"OK: {count} refs across {len(pack.curriculum.tree.nodes)} nodes resolve")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
