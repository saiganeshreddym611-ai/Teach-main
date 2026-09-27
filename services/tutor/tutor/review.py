"""Review status, release sign-off and human audit records for content packs."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .content import ContentPack
from .contracts.content import (
    ReviewMeta,
    ReviewStatus,
    ReleaseSignoff,
    USABLE_REVIEW_STATUSES,
)

ItemKind = Literal["node", "task", "practice"]
KIND_GROUPS: dict[ItemKind, str] = {"node": "nodes", "task": "tasks", "practice": "practice"}
REGRESSIONS_PATH = Path(__file__).resolve().parents[1] / "tests" / "evals" / "review" / "regressions.jsonl"
STATUS_ORDER = ("draft", "claude_reviewed", "needs_expert", "signed_off")


class ReviewGateError(RuntimeError):
    """A review or audit action is not allowed."""


def canonical_sha256(data: BaseModel | dict | list) -> str:
    value = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def pack_items(pack: ContentPack) -> dict[str, tuple[ItemKind, dict]]:
    return {
        node.id: ("node", node.model_dump(mode="json"))
        for node in pack.curriculum.tree.nodes
    }


def item_hashes(pack: ContentPack) -> dict[str, str]:
    return {item_id: canonical_sha256(item) for item_id, (_, item) in pack_items(pack).items()}


def load_reviews(pack: ContentPack) -> dict[str, ReviewMeta]:
    if not pack.reviews_path.is_file():
        return {}
    data = json.loads(pack.reviews_path.read_text(encoding="utf-8"))
    return {item_id: ReviewMeta.model_validate(value) for item_id, value in data.items()}


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(
        json.dumps(value, sort_keys=isinstance(value, dict), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def save_reviews(pack: ContentPack, reviews: dict[str, ReviewMeta]) -> None:
    _atomic_write(
        pack.reviews_path,
        {item_id: reviews[item_id].model_dump(mode="json") for item_id in sorted(reviews)},
    )


def load_releases(pack: ContentPack) -> list[ReleaseSignoff]:
    if not pack.releases_path.is_file():
        return []
    data = json.loads(pack.releases_path.read_text(encoding="utf-8"))
    return [ReleaseSignoff.model_validate(value) for value in data]


def effective_status(item_id: str, current_hash: str, reviews: dict[str, ReviewMeta]) -> ReviewStatus:
    review = reviews.get(item_id)
    if review is None or review.content_sha256 != current_hash:
        return "draft"
    return review.status


def status_table(pack: ContentPack) -> dict[str, tuple[ItemKind, ReviewStatus]]:
    reviews = load_reviews(pack)
    hashes = item_hashes(pack)
    return {
        item_id: (kind, effective_status(item_id, hashes[item_id], reviews))
        for item_id, (kind, _) in pack_items(pack).items()
    }


def review_counts(pack: ContentPack) -> dict[str, dict[str, int]]:
    counts = {group: {status: 0 for status in STATUS_ORDER} for group in KIND_GROUPS.values()}
    for kind, status in status_table(pack).values():
        counts[KIND_GROUPS[kind]][status] += 1
    return counts


def current_release(pack: ContentPack) -> ReleaseSignoff | None:
    for release in reversed(load_releases(pack)):
        if release.content_hash == pack.content_hash and release.version == pack.manifest.version:
            return release
    return None


def strict_problems(pack: ContentPack) -> list[dict]:
    problems = [
        {"item_id": item_id, "kind": kind, "status": status}
        for item_id, (kind, status) in status_table(pack).items()
        if status not in USABLE_REVIEW_STATUSES
    ]
    problems.sort(key=lambda item: item["item_id"])
    if current_release(pack) is None:
        problems.append({"item_id": "<release>", "kind": "release", "status": "missing"})
    return problems


def sample_for_signoff(pack: ContentPack, seed: int | None = None) -> tuple[int, list[str]]:
    chosen_seed = int(pack.content_hash[:8], 16) if seed is None else seed
    candidates = sorted(
        item_id for item_id, (_, status) in status_table(pack).items() if status == "claude_reviewed"
    )
    size = min(len(candidates), max(10, math.ceil(0.10 * len(candidates))))
    return chosen_seed, sorted(random.Random(chosen_seed).sample(candidates, size))


def _validated_items(pack: ContentPack, item_ids: list[str]) -> dict[str, str]:
    hashes = item_hashes(pack)
    missing = sorted(set(item_ids) - set(hashes))
    if missing:
        raise ReviewGateError(f"Unknown item IDs: {', '.join(missing)}")
    return hashes


def _append_note(existing: str, note: str) -> str:
    return f"{existing}\n{note}" if existing else note


def record_pass(pack: ContentPack, item_ids: list[str], by: str, note: str = "") -> None:
    hashes = _validated_items(pack, item_ids)
    reviews = load_reviews(pack)
    invalid = [
        item_id
        for item_id in item_ids
        if effective_status(item_id, hashes[item_id], reviews) not in {"claude_reviewed", "needs_expert"}
    ]
    if invalid:
        raise ReviewGateError(f"Items are not ready for sign-off: {', '.join(sorted(invalid))}")
    now = datetime.now(timezone.utc)
    for item_id in item_ids:
        existing = reviews.get(item_id)
        reviews[item_id] = ReviewMeta(
            status="signed_off",
            content_sha256=hashes[item_id],
            reviewer=existing.reviewer if existing else None,
            claims=existing.claims if existing else [],
            report_id=existing.report_id if existing else None,
            signed_off_by=by,
            signed_off_at=now,
            notes=_append_note(existing.notes if existing else "", note) if note else (existing.notes if existing else ""),
        )
    save_reviews(pack, reviews)


def record_error(pack: ContentPack, item_ids: list[str], by: str, note: str) -> None:
    if not note.strip():
        raise ReviewGateError("An audit error requires a note")
    hashes = _validated_items(pack, item_ids)
    reviews = load_reviews(pack)
    now = datetime.now(timezone.utc)
    stamp = now.date().isoformat()
    for item_id in item_ids:
        existing = reviews.get(item_id)
        audit_note = f"[audit error {stamp} by {by}] {note}"
        reviews[item_id] = ReviewMeta(
            status="draft",
            content_sha256=hashes[item_id],
            reviewer=existing.reviewer if existing else None,
            claims=existing.claims if existing else [],
            report_id=existing.report_id if existing else None,
            signed_off_by=existing.signed_off_by if existing else None,
            signed_off_at=existing.signed_off_at if existing else None,
            notes=_append_note(existing.notes if existing else "", audit_note),
        )
    save_reviews(pack, reviews)
    REGRESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGRESSIONS_PATH.open("a", encoding="utf-8", newline="\n") as output:
        for item_id in item_ids:
            kind, item = pack_items(pack)[item_id]
            output.write(
                json.dumps(
                    {
                        "pack_id": pack.pack_id,
                        "kind": kind,
                        "item_id": item_id,
                        "content_sha256": hashes[item_id],
                        "item": item,
                        "note": note,
                        "by": by,
                        "at": now.isoformat(),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            )


def record_release(pack: ContentPack, by: str, scope_note: str = "") -> ReleaseSignoff:
    problems = [
        problem for problem in strict_problems(pack) if problem["kind"] != "release"
    ]
    if problems:
        raise ReviewGateError(
            "Cannot sign off release; unusable items: "
            + ", ".join(problem["item_id"] for problem in problems)
        )
    release = ReleaseSignoff(
        pack_id=pack.pack_id,
        version=pack.manifest.version,
        content_hash=pack.content_hash,
        signed_off_by=by,
        signed_off_at=datetime.now(timezone.utc),
        scope_note=scope_note,
    )
    releases = load_releases(pack)
    releases.append(release)
    _atomic_write(pack.releases_path, [item.model_dump(mode="json") for item in releases])
    return release
