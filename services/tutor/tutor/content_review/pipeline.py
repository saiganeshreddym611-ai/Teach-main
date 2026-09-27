"""Review runs: build packets, collect answers, decide, record through T11, write the report.

Files for a run live in `<review_dir>/runs/<run_id>/`: `run.json`, and per item `<id>.packet.json`,
`<id>.md` (session mode: the packet to read) and `<id>.answers.json`. The report is
`<review_dir>/<run_id>.md`.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..config import settings
from ..content import ContentPack, clear_pack_cache, load_pack
from ..retrieval import get_retriever
from ..review import item_hashes, record_claude_review, status_table
from .claims import split_node
from .decide import AnswersError, check_answers, decide, validate_answers
from .evidence import build_packet, render_packet
from .models import Answers, ItemResult, Packet, ReviewRun, SelfTestScore
from .reviewers import REVIEW_INSTRUCTIONS, Reviewer, get_reviewer

PLANTED_PATH = Path(__file__).resolve().parents[2] / "tests" / "evals" / "review" / "planted_nodes.json"
SELF_TEST_TARGET = 0.95  # D1: at least 95% of planted errors caught


class ContentReviewError(RuntimeError):
    """A review run cannot start or be ingested."""


def new_run_id(pack_id: str) -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{pack_id}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _run_dir(review_dir: Path, run_id: str) -> Path:
    return review_dir / "runs" / run_id


def review_pack(
    pack: ContentPack,
    item_ids: list[str] | None = None,
    *,
    reviewer: Reviewer | None = None,
    run_id: str | None = None,
    review_dir: Path | None = None,
    self_test: dict[str, str | None] | None = None,
) -> ReviewRun:
    """Review the given nodes, or every node whose effective status is draft (new or edited).
    Returns a pending run in session mode, a done run otherwise."""
    reviewer = reviewer or get_reviewer()
    review_dir = review_dir or settings.review_dir
    retriever = get_retriever(pack)
    if retriever is None:
        raise ContentReviewError(f"No corpus for {pack.pack_id}: run scripts/ingest.py first")
    hashes = item_hashes(pack)
    if item_ids is None:
        item_ids = [i for i, (kind, status) in status_table(pack).items() if kind == "node" and status == "draft"]
    unknown = sorted(set(item_ids) - set(hashes))
    if unknown:
        raise ContentReviewError(f"Unknown item IDs: {', '.join(unknown)}")
    if not item_ids:
        raise ContentReviewError("Nothing to review: no draft nodes. Use --items to review nodes again.")

    run_id = run_id or new_run_id(pack.pack_id)
    run_dir = _run_dir(review_dir, run_id)
    if run_dir.exists():
        raise ContentReviewError(f"Run {run_id} already exists")
    packets: list[Packet] = []
    for item_id in item_ids:
        node = pack.curriculum.node(item_id)
        packet = build_packet(run_id, node, split_node(node), retriever, hashes[item_id])
        _write_json(run_dir / f"{item_id}.packet.json", packet.model_dump(mode="json"))
        packets.append(packet)

    run = ReviewRun(
        run_id=run_id,
        pack_id=pack.pack_id,
        packs_dir=str(pack.root.parent.resolve()),
        reviewer=reviewer.info,
        items=list(item_ids),
        self_test=self_test,
    )
    answers: dict[str, Answers] = {}
    for packet in packets:
        result = reviewer.review(packet)
        if result is None:
            _write(run_dir / f"{packet.item_id}.md", _session_markdown(packet))
            _write_json(run_dir / f"{packet.item_id}.answers.json", _answers_template(packet))
        else:
            answers[packet.item_id] = result
            _write_json(run_dir / f"{packet.item_id}.answers.json", result.model_dump(mode="json"))
    if len(answers) < len(packets):
        _write_json(run_dir / "run.json", run.model_dump(mode="json"))
        return run
    return _finish(run, pack, packets, answers, review_dir)


def ingest_run(run_id: str, review_dir: Path | None = None) -> ReviewRun:
    """Apply the answers a session reviewer wrote into a pending run's `*.answers.json` files."""
    review_dir = review_dir or settings.review_dir
    run_dir = _run_dir(review_dir, run_id)
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise ContentReviewError(f"No pending run {run_id} in {review_dir}")
    run = ReviewRun.model_validate_json(run_path.read_text(encoding="utf-8"))
    if run.state == "done":
        raise ContentReviewError(f"Run {run_id} was already ingested")
    clear_pack_cache()
    pack = load_pack(run.pack_id, Path(run.packs_dir))
    hashes = item_hashes(pack)
    packets: list[Packet] = []
    answers: dict[str, Answers] = {}
    for item_id in run.items:
        packet = Packet.model_validate_json((run_dir / f"{item_id}.packet.json").read_text(encoding="utf-8"))
        if hashes.get(item_id) != packet.content_sha256:
            raise ContentReviewError(f"{item_id} changed since run {run_id} was built; start a new run")
        path = run_dir / f"{item_id}.answers.json"
        try:
            answers[item_id] = Answers.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise ContentReviewError(f"{path}: missing, not filled in, or invalid:\n{exc}") from exc
        packets.append(packet)
    return _finish(run, pack, packets, answers, review_dir)


def _finish(run: ReviewRun, pack: ContentPack, packets: list[Packet], answers: dict[str, Answers], review_dir: Path) -> ReviewRun:
    results: list[ItemResult] = []
    for packet in packets:
        item_answers = answers[packet.item_id]
        try:
            validate_answers(packet, item_answers)
        except AnswersError as exc:
            raise ContentReviewError(str(exc)) from exc
        checked = check_answers(packet, item_answers)
        status, reasons = decide(checked, item_answers.coverage_gaps, packet.unresolved_refs)
        results.append(ItemResult(item_id=packet.item_id, status=status, reasons=reasons,
                                  claims=[c.review_claim() for c in checked]))

    if run.reviewer is None:
        run.notes.append("Mock reviewer: nothing was recorded in reviews.json.")
    else:
        for packet, result in zip(packets, results):
            summary = "; ".join(result.reasons) if result.reasons else "all claims passed"
            record_claude_review(
                pack, result.item_id, result.status, result.claims, run.reviewer, run.run_id,
                notes=f"[claude review {run.run_id}] {summary}", expected_sha256=packet.content_sha256,
            )
    run.results = results
    if run.self_test is not None:
        run.score = _score(run.self_test, results)
    report = review_dir / f"{run.run_id}.md"
    run.report_path = str(report)
    run.state = "done"
    _write(report, _report(run, pack, packets))
    _write_json(_run_dir(review_dir, run.run_id) / "run.json", run.model_dump(mode="json"))
    return run


def _score(expectations: dict[str, str | None], results: list[ItemResult]) -> SelfTestScore:
    status = {r.item_id: r.status for r in results}
    planted = sorted(i for i, kind in expectations.items() if kind)
    clean = sorted(i for i, kind in expectations.items() if not kind)
    missed = [i for i in planted if status.get(i) != "needs_expert"]
    false_alarms = [i for i in clean if status.get(i) != "claude_reviewed"]
    return SelfTestScore(planted=len(planted), caught=len(planted) - len(missed), clean=len(clean),
                         clean_passed=len(clean) - len(false_alarms), missed=missed, false_alarms=false_alarms)


def build_self_test_pack(source: ContentPack, packs_dir: Path, planted_path: Path = PLANTED_PATH) -> tuple[ContentPack, dict[str, str | None]]:
    """Copy the source pack (corpus included, raw sources and review files excluded) and replace
    its concept map with the planted-error nodes. Returns the copy and the expectations."""
    data = json.loads(planted_path.read_text(encoding="utf-8"))
    dest = packs_dir / source.pack_id
    if dest.exists():
        raise ContentReviewError(f"{dest} already exists")
    shutil.copytree(source.root, dest, ignore=shutil.ignore_patterns("raw", "reviews.json", "releases.json", "concept_map.json"))
    _write_json(dest / "concept_map.json", data["tree"])
    clear_pack_cache()
    return load_pack(source.pack_id, packs_dir), data["expectations"]


def _answers_template(packet: Packet) -> dict:
    return {
        "item_id": packet.item_id,
        "answers": [{"claim_id": c.claim_id, "verdict": "", "passage_id": None, "quote": ""} for c in packet.claims],
        "coverage_gaps": [],
    }


def _session_markdown(packet: Packet) -> str:
    return (
        render_packet(packet)
        + "\n## How to answer\n\n"
        + REVIEW_INSTRUCTIONS
        + f"\n\nWrite the answers in `{packet.item_id}.answers.json` next to this file: for each claim, "
        "`verdict` is supported, contradicted or not_found.\n"
    )


def _report(run: ReviewRun, pack: ContentPack, packets: list[Packet]) -> str:
    by_id = {p.item_id: p for p in packets}
    counts = {s: sum(r.status == s for r in run.results) for s in ("claude_reviewed", "needs_expert")}
    reviewer = f"{run.reviewer.mode} ({run.reviewer.model})" if run.reviewer else "mock"
    lines = [
        f"# Content review report: {run.run_id}",
        "",
        f"- Pack: {pack.pack_id}, version {pack.manifest.version}, content hash {pack.content_hash[:12]}",
        f"- Reviewer: {reviewer}",
        f"- Items: {len(run.results)}; claude_reviewed: {counts['claude_reviewed']}; needs_expert: {counts['needs_expert']}",
    ]
    lines += [f"- {note}" for note in run.notes]
    if run.score is not None:
        s = run.score
        verdict = "meets" if s.catch_rate >= SELF_TEST_TARGET else "BELOW"
        lines += [
            f"- Self-test: planted errors caught {s.caught}/{s.planted} ({s.catch_rate:.0%}), {verdict} the "
            f"{SELF_TEST_TARGET:.0%} target; clean nodes passed {s.clean_passed}/{s.clean}",
        ]
        if s.missed:
            lines.append(f"- Missed: {', '.join(s.missed)}")
        if s.false_alarms:
            lines.append(f"- False alarms: {', '.join(s.false_alarms)}")
    lines += ["", "| Item | Status | Findings |", "|---|---|---|"]
    lines += [f"| {r.item_id} | {r.status} | {len(r.reasons)} |" for r in run.results]
    for result in run.results:
        packet = by_id[result.item_id]
        lines += ["", f"## {result.item_id}: {packet.title}", "", f"Status: **{result.status}**"]
        if run.self_test is not None:
            lines.append(f"Planted error: {run.self_test.get(result.item_id) or 'none (clean node)'}")
        if result.reasons:
            lines += ["", "Findings:"] + [f"- {reason}" for reason in result.reasons]
        labels = {p.passage_id: p.label for p in packet.passages}
        lines += ["", "| Claim | Verdict | Source | Quote checked |", "|---|---|---|---|"]
        for claim, rc in zip(packet.claims, result.claims):
            source = labels.get(rc.passage_id, "") if rc.passage_id else ""
            text = rc.claim.replace("|", "/")
            lines.append(f"| {claim.claim_id} {claim.kind}: {text} | {rc.verdict} | {source} | {'yes' if rc.quote_verified else 'no'} |")
    return "\n".join(lines) + "\n"
