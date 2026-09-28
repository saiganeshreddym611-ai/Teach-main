"""Calibrate the deterministic retrieval confidence threshold."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tutor.content import load_pack
from tutor.retrieval import get_retriever


def calibrate(retriever: Any, queries: list[dict[str, Any]], k: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for query in queries:
        results = retriever.search(str(query["query"]), k=k)
        ids = [item.passage.passage_id for item in results]
        confidence = results[0].confidence if results else 0.0
        expected = set(query.get("expected", []))
        rows.append(
            {
                "id": query.get("id", ""),
                "in_syllabus": bool(query.get("in_syllabus", False)),
                "confidence": confidence,
                "top_k": ids,
                "recall": len(expected.intersection(ids)) / len(expected) if expected else 0.0,
            }
        )
    in_rows = [row for row in rows if row["in_syllabus"]]
    out_rows = [row for row in rows if not row["in_syllabus"]]
    recall = sum(row["recall"] for row in in_rows) / len(in_rows) if in_rows else 0.0
    values = sorted({row["confidence"] for row in rows})
    candidates = [(left + right) / 2.0 for left, right in zip(values, values[1:])]
    if candidates:
        def candidate_key(threshold: float) -> tuple[float, float, float]:
            accuracy = sum(
                (row["confidence"] >= threshold) == row["in_syllabus"] for row in rows
            ) / len(rows) if rows else 0.0
            distance = min(abs(threshold - value) for value in values)
            return accuracy, distance, -threshold

        threshold = max(candidates, key=candidate_key)
    else:
        threshold = 0.5
    accuracy = (
        sum((row["confidence"] >= threshold) == row["in_syllabus"] for row in rows) / len(rows)
        if rows else 0.0
    )
    in_confidences = [row["confidence"] for row in in_rows]
    out_confidences = [row["confidence"] for row in out_rows]
    margin = (min(in_confidences) if in_confidences else 0.0) - (
        max(out_confidences) if out_confidences else 0.0
    )
    return {
        "queries": rows,
        "recall_at_k": recall,
        "threshold": threshold,
        "accuracy": accuracy,
        "margin": margin,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    parser.add_argument(
        "--queries",
        type=Path,
        default=SERVICE_ROOT / "tests" / "evals" / "retrieval" / "queries.jsonl",
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--mode", choices=["bm25", "hybrid"], default="bm25")
    parser.add_argument("--reworded-only", action="store_true")
    args = parser.parse_args(argv)
    queries = [
        json.loads(line)
        for line in args.queries.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.reworded_only:
        queries = [q for q in queries if q.get("reworded")]
    queries = [query for query in queries if query.get("pack") == args.pack]

    from tutor.config import settings
    import os
    os.environ["RETRIEVAL_MODE"] = args.mode
    # Note: settings is a singleton, so we need to update it or restart process.
    # Since we are in a script, we can just patch settings.
    settings.retrieval_mode = args.mode

    retriever = get_retriever(load_pack(args.pack, packs_dir=args.packs_dir))
    if retriever is None:
        parser.error(f"pack '{args.pack}' has no corpus")
    result = calibrate(retriever, queries, args.k)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("id\tin_syllabus\tconfidence\trecall\ttop_k")
        for row in result["queries"]:
            print(f'{row["id"]}\t{row["in_syllabus"]}\t{row["confidence"]:.6f}\t{row["recall"]:.6f}\t{",".join(row["top_k"])}')
        print(
            f'recall_at_k={result["recall_at_k"]:.6f} threshold={result["threshold"]:.6f} '
            f'accuracy={result["accuracy"]:.6f} margin={result["margin"]:.6f}'
        )
    return 0 if result["recall_at_k"] >= args.min_recall else 1


if __name__ == "__main__":
    sys.exit(main())
