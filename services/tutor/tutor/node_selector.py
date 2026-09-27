"""Pure-code implementation of "Identify Deepest Missing Node".

Two orders, chosen by the study mode after the diagnostic:
- breadth-first (revision): Level 1 -> 2 -> 3, each in document order, so every
  heading is checked before any detail;
- depth-first (learning): plain document order, so a heading and all its
  subtopics are taught before the next heading.
Either way the first node that is not VERIFIED and not parked is returned.
Parked nodes (max teach-back attempts exhausted) are only revisited once
everything else is verified.
"""
from __future__ import annotations

from .curriculum import Curriculum
from .models import NodeStatus


def select_next_node(
    curriculum: Curriculum,
    status: dict[str, NodeStatus],
    parked: list[str],
    *,
    max_level: int = 3,
    depth_first: bool = False,
) -> str | None:
    candidates = [n for n in curriculum.tree.nodes if n.level <= max_level]
    if depth_first:
        # Walk the tree itself, so the order holds whatever order the concept map lists nodes in.
        roots = [n.id for n in curriculum.tree.nodes if n.parent is None]
        rank = {nid: i for i, nid in enumerate(nid for root in roots for nid in curriculum.subtree_ids(root))}
        candidates.sort(key=lambda n: rank[n.id])
    else:
        candidates.sort(key=lambda n: (n.level, curriculum.order[n.id]))
    def deferred(node_id: str) -> bool:
        # Depth-first also defers a parked heading's subtopics: come back to the whole topic later.
        return node_id in parked or (depth_first and any(a.id in parked for a in curriculum.ancestors(node_id)))

    for n in candidates:
        if deferred(n.id):
            continue
        if status.get(n.id, NodeStatus.NOT_MENTIONED) != NodeStatus.VERIFIED:
            return n.id
    # Everything else is verified - give deferred nodes another go, in order.
    for n in candidates:
        if deferred(n.id) and status.get(n.id) != NodeStatus.VERIFIED:
            return n.id
    return None
