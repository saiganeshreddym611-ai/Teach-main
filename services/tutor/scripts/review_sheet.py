"""Write a deterministic review sheet for human sign-off."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tutor.content import load_pack
from tutor.review import (
    current_release,
    load_reviews,
    pack_items,
    review_counts,
    sample_for_signoff,
    status_table,
)


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _item_block(item_id: str, status: str, item: dict, review) -> list[str]:
    reviewer = review.reviewer if review and review.reviewer else None
    lines = [
        f"### {item_id} — {_escape(item.get('title', item_id))}",
        f"Status: `{status}`",
        f"Reviewer: `{reviewer.mode if reviewer else ''}` / `{reviewer.model if reviewer else ''}`",
        "",
        "| claim | verdict | passage | quote | quote verified |",
        "|---|---|---|---|---|",
    ]
    claims = review.claims if review else []
    for claim in claims:
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    claim.claim,
                    claim.verdict,
                    claim.passage_id or "",
                    claim.quote,
                    claim.quote_verified,
                )
            )
            + " |"
        )
    lines.extend(["", f"Notes: {_escape(review.notes if review else '')}", ""])
    return lines


def build_report(pack, seed: int | None = None) -> str:
    reviews = load_reviews(pack)
    table = status_table(pack)
    release = current_release(pack)
    chosen_seed, sample = sample_for_signoff(pack, seed)
    candidates = [
        item_id for item_id, (_, status) in table.items() if status == "claude_reviewed"
    ]
    lines = [
        f"# Review sheet: {pack.pack_id} {pack.manifest.version}",
        "",
        f"- Exam: {pack.manifest.exam}",
        f"- Paper: {pack.manifest.paper}",
        f"- Attempt: {pack.manifest.attempt}",
        f"- Content hash: `{pack.content_hash}`",
        (
            f"- Release sign-off: {release.signed_off_by} ({release.signed_off_at.isoformat()})"
            if release
            else "- No release sign-off for this content"
        ),
        "",
        "## Counts",
        "",
        "| group | draft | claude_reviewed | needs_expert | signed_off |",
        "|---|---:|---:|---:|---:|",
    ]
    counts = review_counts(pack)
    for group in ("nodes", "tasks", "practice"):
        lines.append(
            f"| {group} | "
            + " | ".join(str(counts[group][status]) for status in ("draft", "claude_reviewed", "needs_expert", "signed_off"))
            + " |"
        )
    lines.extend(["", "## Needs expert", ""])
    for item_id, (kind, status) in table.items():
        if status == "needs_expert":
            lines.extend(_item_block(item_id, status, pack_items_for_report(pack, item_id), reviews.get(item_id)))
    lines.extend([
        f"## Sample for sign-off (seed {chosen_seed}, {len(sample)} of {len(candidates)})",
        "",
    ])
    for item_id in sample:
        kind, status = table[item_id]
        lines.extend(_item_block(item_id, status, pack_items_for_report(pack, item_id), reviews.get(item_id)))
    lines.extend(["## Not yet reviewed", ""])
    for item_id, (kind, status) in table.items():
        if status == "draft":
            item = pack_items_for_report(pack, item_id)
            lines.append(f"- {item_id} — {_escape(item.get('title', item_id))}")
    return "\n".join(lines) + "\n"


def pack_items_for_report(pack, item_id: str) -> dict:
    return pack_items(pack)[item_id][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    pack = load_pack(args.pack, args.packs_dir)
    output = args.out or SERVICE_ROOT / "data" / "reviews" / f"{pack.pack_id}-{pack.manifest.version}-review-sheet.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(pack, args.seed), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
