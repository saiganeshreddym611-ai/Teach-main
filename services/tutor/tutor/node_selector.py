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
from .contracts.jobs import JobProfile
from .jobs import meets
from .models import NodeStatus


def select_next_node(
    curriculum: Curriculum,
    status: dict[str, NodeStatus],
    parked: list[str],
    *,
    max_level: int = 3,
    depth_first: bool = False,
    job_profile: JobProfile | None = None,
) -> str | None:
    candidates = [n for n in curriculum.tree.nodes if n.level <= max_level]
    if job_profile is not None:
        required = {requirement.node_id: requirement for requirement in job_profile.required}
        adjacent = {requirement.node_id: requirement for requirement in job_profile.adjacent}
        candidates = [
            n for n in candidates if n.id in required or n.id in adjacent
        ]
        groups = [
            [n for n in candidates if n.id in required],
            [n for n in candidates if n.id in adjacent],
        ]
    else:
        groups = [candidates]
    if depth_first:
        # Walk the tree itself, so the order holds whatever order the concept map lists nodes in.
        roots = [n.id for n in curriculum.tree.nodes if n.parent is None]
        rank = {nid: i for i, nid in enumerate(nid for root in roots for nid in curriculum.subtree_ids(root))}
        candidates.sort(key=lambda n: rank[n.id])
        for group in groups:
            group.sort(key=lambda n: rank[n.id])
    else:
        candidates.sort(key=lambda n: (n.level, curriculum.order[n.id]))
        for group in groups:
            group.sort(key=lambda n: (n.level, curriculum.order[n.id]))

    def deferred(node_id: str) -> bool:
        # Depth-first also defers a parked heading's subtopics: come back to the whole topic later.
        return node_id in parked or (depth_first and any(a.id in parked for a in curriculum.ancestors(node_id)))

    for group in groups:
        for n in group:
            requirement = (
                (required.get(n.id) if job_profile is not None else None)
                or (adjacent.get(n.id) if job_profile is not None else None)
            )
            done = (
                meets(status.get(n.id), requirement.min_status)
                if requirement is not None
                else status.get(n.id, NodeStatus.NOT_MENTIONED) == NodeStatus.VERIFIED
            )
            if not deferred(n.id) and not done:
                return n.id
    # Everything else is verified - give deferred nodes another go, in order.
    for group in groups:
        for n in group:
            requirement = (
                (required.get(n.id) if job_profile is not None else None)
                or (adjacent.get(n.id) if job_profile is not None else None)
            )
            done = (
                meets(status.get(n.id), requirement.min_status)
                if requirement is not None
                else status.get(n.id, NodeStatus.NOT_MENTIONED) == NodeStatus.VERIFIED
            )
            if deferred(n.id) and not done:
                return n.id
    return None
