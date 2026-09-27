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

from tutor.config import settings  # noqa: E402
from tutor.content import clear_pack_cache, load_pack  # noqa: E402
from tutor.contracts.grading import GraderOutput  # noqa: E402
from tutor.curriculum import Curriculum  # noqa: E402
from tutor.grader import omissions  # noqa: E402
from tutor.grader_audit import citation_diffs, grade_memo  # noqa: E402
from tutor.grading_links import NodeLinks  # noqa: E402
from tutor.llm import describe_grader, get_grader  # noqa: E402
from tutor.models import NodeStatus  # noqa: E402


def check(expect: str, actual: str | None) -> bool:
    actual = actual or NodeStatus.NOT_MENTIONED.value
    if expect.startswith("!"):
        return actual != expect[1:]
    return actual == expect


def check_citations(expect: dict[str, list[str]], runs: list[GraderOutput]) -> list[str]:
    failures: list[str] = []
    for run_index, output in enumerate(runs, start=1):
        verdicts = {verdict.node_id: verdict for verdict in output.verdicts}
        for node_id, prefixes in expect.items():
            passage_ids = verdicts[node_id].passage_ids if node_id in verdicts else []
            for prefix in prefixes:
                if not any(passage_id.startswith(prefix) for passage_id in passage_ids):
                    failures.append(
                        f"  [CITE FAIL] run {run_index} {node_id}: no passage ID starts with {prefix!r}"
                    )
    return failures


def check_omissions(
    expect: list[str],
    curriculum: Curriculum,
    runs: list[GraderOutput],
) -> list[str]:
    failures: list[str] = []
    links = NodeLinks()
    expected = set(expect)
    for run_index, output in enumerate(runs, start=1):
        actual = {item.node_id for item in omissions(curriculum, output, links)}
        if actual != expected:
            failures.append(
                f"  [OMISSION FAIL] run {run_index}: expected {sorted(expected)}, got {sorted(actual)}"
            )
    return failures


def counts_toward_failures(status: str, include_drafts: bool) -> bool:
    return status != "draft" or include_drafts


async def main(
    repeat: int,
    only: str | None,
    use_memo: bool,
    include_drafts: bool,
) -> int:
    cases = sorted(HERE.glob("cases/*.json"))
    if only:
        cases = [path for path in cases if only in path.name]
    cases_by_pack: dict[str, list[tuple[Path, dict]]] = {}
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        cases_by_pack.setdefault(case.get("pack", "ind_as_115"), []).append((path, case))

    failures = 0
    citation_inconsistent = 0
    original_pack = settings.content_pack
    original_grade_memo = settings.grade_memo
    settings.grade_memo = use_memo
    try:
        for pack_id, pack_cases in cases_by_pack.items():
            settings.content_pack = pack_id
            clear_pack_cache()
            get_grader.cache_clear()
            grade_memo.clear()
            curriculum = load_pack().curriculum
            grader = get_grader()
            print(f"grader backend ({pack_id}): {describe_grader()}")
            if use_memo:
                print("memo: ON")

            for path, case in pack_cases:
                grader_outputs: list[GraderOutput] = []
                for _ in range(repeat):
                    result = await grader.grade(
                        curriculum,
                        case["transcript"],
                        focus_node_id=case.get("focus_node_id"),
                        prior_context=case.get("prior_context", ""),
                        session_id=f"eval_{path.stem}",
                    )
                    grader_outputs.append(result)
                status = case.get("status", "reviewed")
                label = "[DRAFT] " if status == "draft" else ""
                print(f"\n== {label}{path.name}: {case['name']}")
                case_failures = 0
                for node_id, expected in case["expect"].items():
                    actuals = [
                        next(
                            (v.status.value for v in output.verdicts if v.node_id == node_id),
                            None,
                        )
                        for output in grader_outputs
                    ]
                    ok = all(check(expected, actual) for actual in actuals)
                    consistent = len(set(actuals)) == 1
                    mark = "PASS" if ok and consistent else "FAIL"
                    if mark == "FAIL":
                        if not ok:
                            case_failures += 1
                        if not consistent:
                            # Status inconsistency is still a failing expectation (counted in N)
                            case_failures += 1
                    shown = (
                        actuals[0]
                        if consistent
                        else f"INCONSISTENT {Counter(a or 'NOT_MENTIONED' for a in actuals)}"
                    )
                    print(f"  [{mark}] {node_id:<48} expect {expected:<14} got {shown}")

                if case.get("expect_citations"):
                    citation_failures = check_citations(
                        case["expect_citations"], grader_outputs
                    )
                    for failure in citation_failures:
                        print(failure)
                    if not citation_failures:
                        print("  [CITE PASS] expected passage prefixes present in every run")
                    case_failures += len(citation_failures)

                if "expect_omissions" in case:
                    omission_failures = check_omissions(
                        case["expect_omissions"], curriculum, grader_outputs
                    )
                    for failure in omission_failures:
                        print(failure)
                    if not omission_failures:
                        print("  [OMISSION PASS] expected level-1 omissions match in every run")
                    case_failures += len(omission_failures)

                if counts_toward_failures(status, include_drafts):
                    failures += case_failures

                if repeat > 1:
                    node_ids = list(case["expect"].keys())
                    diffs = citation_diffs(grader_outputs, node_ids)
                    for diff in diffs:
                        print(diff)
                    if counts_toward_failures(status, include_drafts):
                        citation_inconsistent += len(diffs)

            grade_memo.clear()
    finally:
        settings.content_pack = original_pack
        settings.grade_memo = original_grade_memo
        clear_pack_cache()
        get_grader.cache_clear()
        grade_memo.clear()

    print(
        f"\n{failures} failing expectation(s), {citation_inconsistent} inconsistent citation(s) "
        f"across {len(cases)} case(s), {repeat} run(s) each."
    )
    return 1 if failures > 0 or citation_inconsistent > 0 else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", help="substring filter on case filename")
    ap.add_argument("--memo", action="store_true", help="enable grade memo (default: off for evals)")
    ap.add_argument("--include-drafts", action="store_true", help="count draft case failures")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.repeat, args.only, args.memo, args.include_drafts)))
