"""Grounded content review (T23).

  content_review.py --pack ind_as_115                  review every draft node
  content_review.py --pack ind_as_115 --items a,b      review these nodes (again)
  content_review.py --pack fixture_115 --packs-dir tests/fixtures/packs --self-test
  content_review.py --ingest <run_id>                  apply the answers written in a session run

REVIEWER=session (default) writes packets for Claude to answer in the Claude Code session;
REVIEWER=claude-api answers them through the Anthropic API. Ollama models are refused (D6).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tutor.config import settings
from tutor.content import load_pack
from tutor.content_review.models import ReviewRun
from tutor.content_review.pipeline import (
    SELF_TEST_TARGET,
    ContentReviewError,
    build_self_test_pack,
    ingest_run,
    new_run_id,
    review_pack,
)
from tutor.content_review.reviewers import ReviewerRefused, get_reviewer


def _print_run(run: ReviewRun, review_dir: Path) -> int:
    if run.state == "pending":
        run_dir = review_dir / "runs" / run.run_id
        print(f"{len(run.items)} packets waiting in {run_dir}")
        print("Answer each <item>.answers.json, then run:")
        print(f"  python scripts/content_review.py --ingest {run.run_id}")
        return 0
    for result in run.results:
        print(f"{result.status:16} {result.item_id}  ({len(result.reasons)} findings)")
    for note in run.notes:
        print(note)
    print(f"Report: {run.report_path}")
    if run.score is not None:
        s = run.score
        print(f"Self-test: caught {s.caught}/{s.planted} planted errors ({s.catch_rate:.0%}); "
              f"clean nodes passed {s.clean_passed}/{s.clean}")
        return 0 if s.catch_rate >= SELF_TEST_TARGET else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pack")
    parser.add_argument("--packs-dir", type=Path)
    parser.add_argument("--items", help="comma-separated node IDs")
    parser.add_argument("--ingest", metavar="RUN_ID")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--reviewer", help="session or claude-api (default: REVIEWER)")
    parser.add_argument("--review-dir", type=Path, default=settings.review_dir)
    args = parser.parse_args(argv)
    try:
        if args.ingest:
            return _print_run(ingest_run(args.ingest, args.review_dir), args.review_dir)
        if not args.pack:
            parser.error("--pack is required unless --ingest is given")
        reviewer = get_reviewer(args.reviewer)
        pack = load_pack(args.pack, packs_dir=args.packs_dir)
        if args.self_test:
            run_id = new_run_id(f"{pack.pack_id}-selftest")
            pack, expectations = build_self_test_pack(pack, args.review_dir / "selftest" / run_id)
            run = review_pack(pack, reviewer=reviewer, run_id=run_id, review_dir=args.review_dir, self_test=expectations)
        else:
            items = [i.strip() for i in args.items.split(",") if i.strip()] if args.items else None
            run = review_pack(pack, items, reviewer=reviewer, review_dir=args.review_dir)
    except (ContentReviewError, ReviewerRefused) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _print_run(run, args.review_dir)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
