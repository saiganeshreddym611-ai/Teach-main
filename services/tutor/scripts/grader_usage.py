"""Summarise grader capture files for token/cost accounting.

Usage:
    python scripts/grader_usage.py [--dir PATH]

The capture directory defaults to settings.grader_capture_dir.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import defaultdict

from tutor.config import settings


def summarise(records: list[dict]) -> dict[str, dict[str, float | int]]:
    """Summarise capture records by phase.

    Returns a dict mapping phase -> totals with keys:
    calls, memo_hits, input, cache_read, cache_write, output, mean_latency_ms
    """
    by_phase: dict[str, dict] = defaultdict(lambda: {
        "calls": 0,
        "memo_hits": 0,
        "input": 0,
        "cache_read": 0,
        "cache_write": 0,
        "output": 0,
        "latency_sum": 0,
    })
    for r in records:
        phase = r.get("phase", "unknown")
        p = by_phase[phase]
        p["calls"] += 1
        if r.get("memo_hit"):
            p["memo_hits"] += 1
        usage = r.get("usage") or {}
        # Claude keys - use get(key) or 0 to handle null values
        if "input_tokens" in usage:
            p["input"] += usage.get("input_tokens") or 0
            p["cache_read"] += usage.get("cache_read_input_tokens") or 0
            p["cache_write"] += usage.get("cache_creation_input_tokens") or 0
            p["output"] += usage.get("output_tokens") or 0
        # Ollama keys
        elif "prompt_eval_count" in usage:
            p["input"] += usage.get("prompt_eval_count") or 0
            p["output"] += usage.get("eval_count") or 0
        p["latency_sum"] += r.get("latency_ms", 0)

    result: dict[str, dict[str, float | int]] = {}
    for phase, p in by_phase.items():
        result[phase] = {
            "calls": p["calls"],
            "memo_hits": p["memo_hits"],
            "input": p["input"],
            "cache_read": p["cache_read"],
            "cache_write": p["cache_write"],
            "output": p["output"],
            "mean_latency_ms": round(p["latency_sum"] / p["calls"]) if p["calls"] else 0,
        }
    return result


def load_captures(dir_path: Path) -> list[dict]:
    records = []
    for path in sorted(dir_path.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return records


def print_table(summary: dict[str, dict[str, float | int]]) -> None:
    headers = ["phase", "calls", "memo_hits", "input", "cache_read", "cache_write", "output", "mean_latency_ms"]
    print(" | ".join(f"{h:>14}" for h in headers))
    print("-" * (len(headers) * 16))
    for phase, totals in summary.items():
        row = [
            phase,
            str(totals["calls"]),
            str(totals["memo_hits"]),
            str(totals["input"]),
            str(totals["cache_read"]),
            str(totals["cache_write"]),
            str(totals["output"]),
            str(totals["mean_latency_ms"]),
        ]
        print(" | ".join(f"{c:>14}" for c in row))
    # Grand total
    grand = {k: sum(t[k] for t in summary.values()) for k in headers[1:]}
    grand["mean_latency_ms"] = sum(t["mean_latency_ms"] * t["calls"] for t in summary.values()) / grand["calls"] if grand["calls"] else 0
    row = ["TOTAL", *[str(grand[k]) for k in headers[1:]]]
    print("-" * (len(headers) * 16))
    print(" | ".join(f"{c:>14}" for c in row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=settings.grader_capture_dir, help="Capture directory")
    args = ap.parse_args()

    records = load_captures(args.dir)
    if not records:
        print(f"No captures found in {args.dir}")
        return 0

    summary = summarise(records)
    print_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
