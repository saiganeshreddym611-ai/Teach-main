"""Evidence packets: the passages a reviewer may use to judge one node's claims."""
from __future__ import annotations

from ..models import Node
from ..retrieval import PackRetriever, UnresolvedRef, passage_label, resolve_ref
from ..contracts.content import Passage
from .models import Claim, Packet, PacketPassage

SEARCH_K = 3  # search hits kept per claim
MAX_SEARCH_PASSAGES = 8  # search hits kept per packet

COVERAGE_QUESTION = (
    "List each requirement, condition or exception that the [linked] passages state for this "
    "concept and that none of the rubric claims covers. Return an empty list when the rubric "
    "covers them all."
)


def _superseded_by(retriever: PackRetriever) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for passage in retriever.corpus.by_id.values():
        for old in passage.supersedes:
            out.setdefault(old, []).append(passage.passage_id)
    return {old: sorted(new) for old, new in out.items()}


def build_packet(run_id: str, node: Node, claims: list[Claim], retriever: PackRetriever, content_sha256: str) -> Packet:
    """The node's own linked passages first, in source_refs order. Then, per claim, up to SEARCH_K
    search hits from documents at least as authoritative as the least authoritative document the
    node already cites (standards only when it cites nothing), capped at MAX_SEARCH_PASSAGES."""
    corpus = retriever.corpus
    unresolved = []
    for ref in node.source_refs:
        try:
            resolve_ref(ref, corpus)
        except UnresolvedRef:
            unresolved.append(ref)
    linked = retriever.for_node(node.id)
    seen = {p.passage_id for p in linked}
    ceiling = max((corpus.doc(p.doc_id).authority_rank for p in linked), default=1)

    extra: list[Passage] = []
    for claim in claims:
        kept = 0
        for hit in retriever.search(claim.text, k=SEARCH_K * 4):
            passage = hit.passage
            if passage.passage_id in seen or corpus.doc(passage.doc_id).authority_rank > ceiling:
                continue
            seen.add(passage.passage_id)
            extra.append(passage)
            kept += 1
            if kept == SEARCH_K:
                break
    extra = extra[:MAX_SEARCH_PASSAGES]

    superseded = _superseded_by(retriever)
    passages = [
        PacketPassage(
            passage_id=p.passage_id,
            label=passage_label(p, corpus.doc(p.doc_id)),
            text=p.text,
            linked=is_linked,
            superseded_by=superseded.get(p.passage_id, []),
        )
        for p, is_linked in [(p, True) for p in linked] + [(p, False) for p in extra]
    ]
    return Packet(
        run_id=run_id,
        item_id=node.id,
        title=node.title,
        content_sha256=content_sha256,
        source_refs=list(node.source_refs),
        unresolved_refs=unresolved,
        claims=claims,
        passages=passages,
        coverage_question=COVERAGE_QUESTION,
    )


def render_packet(packet: Packet) -> str:
    """The packet as the reviewer reads it. Expectations are left out so the verdict is not led."""
    lines = [
        f"# Review packet: {packet.item_id}",
        "",
        f"Node: {packet.title}",
        f"Source refs: {', '.join(packet.source_refs) or '(none)'}",
    ]
    if packet.unresolved_refs:
        lines.append(f"Unresolved refs: {', '.join(packet.unresolved_refs)}")
    lines += ["", "## Claims", ""]
    lines += [f"- {c.claim_id} ({c.kind}): {c.text}" for c in packet.claims]
    lines += ["", "## Passages", ""]
    for p in packet.passages:
        tag = "linked" if p.linked else "search"
        note = f" (superseded by {', '.join(p.superseded_by)})" if p.superseded_by else ""
        lines += [f"### [{tag}] {p.passage_id}: {p.label}{note}", "", p.text, ""]
    lines += ["## Coverage question", "", packet.coverage_question, ""]
    return "\n".join(lines)
