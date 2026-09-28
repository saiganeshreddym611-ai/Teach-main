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
    # Minimum status per node: VERIFIED for the whole tree, or the profile's own minimums.
    minimum: dict[str, str] = {n.id: "VERIFIED" for n in candidates}
    if job_profile is not None:
        minimum = {r.node_id: r.min_status for r in job_profile.required + job_profile.adjacent}
        required = {r.node_id for r in job_profile.required}
        groups = [[n for n in candidates if n.id in required],
                  [n for n in candidates if n.id in minimum and n.id not in required]]
    else:
        groups = [candidates]
    if depth_first:
        # Walk the tree itself, so the order holds whatever order the concept map lists nodes in.
        roots = [n.id for n in curriculum.tree.nodes if n.parent is None]
        rank = {nid: i for i, nid in enumerate(nid for root in roots for nid in curriculum.subtree_ids(root))}
        order = lambda n: rank[n.id]  # noqa: E731
    else:
        order = lambda n: (n.level, curriculum.order[n.id])  # noqa: E731
    ordered = [n.id for group in groups for n in sorted(group, key=order)]

    def deferred(node_id: str) -> bool:
        # Depth-first also defers a parked heading's subtopics: come back to the whole topic later.
        return node_id in parked or (depth_first and any(a.id in parked for a in curriculum.ancestors(node_id)))

    todo = [nid for nid in ordered if not meets(status.get(nid, NodeStatus.NOT_MENTIONED), minimum[nid])]
    # Deferred nodes get another go only once everything else is done.
    return next((nid for nid in todo if not deferred(nid)), None) or next(iter(todo), None)
