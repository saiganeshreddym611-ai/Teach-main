"""Check a content pack: concept-map references resolve, and skills and tasks are consistent.

Exit 0 when everything passes (warnings allowed), 1 when any check fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tutor.content import ContentPackError, load_pack
from tutor.retrieval.corpus import load_corpus
from tutor.retrieval.refs import UnresolvedRef, resolve_ref
from tutor.jobs import load_job_profiles
from tutor.skills.checks import check_jobs, check_skills
from tutor.skills.loader import load_skills, load_tasks


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    args = parser.parse_args(argv)
    pack = load_pack(args.pack, packs_dir=args.packs_dir)
    corpus = load_corpus(pack)
    failures: list[str] = []
    warnings: list[str] = []

    ref_count = 0
    if corpus is None:
        warnings.append(f"No corpus for {args.pack}: source_refs were not checked (run scripts/ingest.py)")
    else:
        for node in pack.curriculum.tree.nodes:
            for ref in node.source_refs:
                ref_count += 1
                try:
                    resolve_ref(ref, corpus)
                except UnresolvedRef as exc:
                    failures.append(f"{node.id}  {ref}  {exc.reason}")

    try:
        skills, tasks = load_skills(pack), load_tasks(pack)
    except ContentPackError as exc:
        failures.append(str(exc))
        skills, tasks = {}, {}
    report = check_skills(pack, skills, tasks, corpus)
    try:
        failures += check_jobs(load_job_profiles(pack), skills)
    except ContentPackError as exc:
        failures.append(str(exc))
    failures += report.failures
    warnings += report.warnings

    for warning in warnings:
        print(f"WARNING: {warning}")
    if failures:
        print("\n".join(f"FAIL: {failure}" for failure in failures))
        return 1
    refs = f"{ref_count} refs across {len(pack.curriculum.tree.nodes)} nodes resolve" if corpus else "refs not checked"
    print(f"OK: {refs}; {len(skills)} skills and {len(tasks)} tasks are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
