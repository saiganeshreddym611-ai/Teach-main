"""Run the configured grader (GRADER_PROVIDER in .env: claude | ollama) against the
hand-written cases. Claude needs ANTHROPIC_API_KEY; Ollama needs the server + model.

    python tests/evals/grader/run_evals.py            # one pass
    python tests/evals/grader/run_evals.py --repeat 3 # consistency check
    python tests/evals/grader/run_evals.py --memo     # enable memo (default: off for evals)

Expectation syntax per node: VERIFIED | PARTIAL | GAP | NOT_MENTIONED | !VERIFIED
NOT_MENTIONED passes if the verdict is absent or explicitly NOT_MENTIONED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from tutor.curriculum import load_curriculum  # noqa: E402
from tutor.grader_audit import citation_diffs, grade_memo  # noqa: E402
from tutor.llm import describe_grader, get_grader  # noqa: E402
from tutor.models import NodeStatus  # noqa: E402


def check(expect: str, actual: str | None) -> bool:
    actual = actual or NodeStatus.NOT_MENTIONED.value
    if expect.startswith("!"):
        return actual != expect[1:]
    return actual == expect


async def main(repeat: int, only: str | None, use_memo: bool) -> int:
    curriculum = load_curriculum("ind_as_115")
    grader = get_grader()
    print(f"grader backend: {describe_grader()}")
    if use_memo:
        print("memo: ON")
    else:
        # Turn off memo for evals unless explicitly requested
        from tutor.config import settings
        settings.grade_memo = False
    cases = sorted(HERE.glob("cases/*.json"))
    if only:
        cases = [c for c in cases if only in c.name]
    failures = 0
    citation_inconsistent = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        runs: list[dict[str, str]] = []
        grader_outputs: list = []
        for _ in range(repeat):
            res = await grader.grade(
                curriculum,
                case["transcript"],
                focus_node_id=case.get("focus_node_id"),
                prior_context=case.get("prior_context", ""),
                session_id=f"eval_{path.stem}",
            )
            runs.append({v.node_id: v.status.value for v in res.verdicts})
            grader_outputs.append(res)
        print(f"\n== {path.name}: {case['name']}")
        for node_id, expect in case["expect"].items():
            actuals = [r.get(node_id) for r in runs]
            ok = all(check(expect, a) for a in actuals)
            consistent = len(set(actuals)) == 1
            mark = "PASS" if ok and consistent else "FAIL"
            if mark == "FAIL":
                if not ok:
                    failures += 1
                if not consistent:
                    # Status inconsistency is still a failing expectation (counted in N)
                    failures += 1
            shown = actuals[0] if consistent else f"INCONSISTENT {Counter(a or 'NOT_MENTIONED' for a in actuals)}"
            print(f"  [{mark}] {node_id:<48} expect {expect:<14} got {shown}")
        # Citation diffs
        if repeat > 1:
            node_ids = list(case["expect"].keys())
            diffs = citation_diffs(grader_outputs, node_ids)
            for d in diffs:
                print(d)
            citation_inconsistent += len(diffs)
    print(f"\n{failures} failing expectation(s), {citation_inconsistent} inconsistent citation(s) across {len(cases)} case(s), {repeat} run(s) each.")
    return 1 if failures > 0 or citation_inconsistent > 0 else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", help="substring filter on case filename")
    ap.add_argument("--memo", action="store_true", help="enable grade memo (default: off for evals)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.repeat, args.only, args.memo)))
