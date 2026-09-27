"""Knowledge-tree model and prompt-stable serialisation."""
from __future__ import annotations

import json

from .models import Node, Tree

PROMPT_TREE_FIELDS = ("topic_id", "subject", "standard", "opening_prompt")
PROMPT_NODE_FIELDS = (
    "id",
    "level",
    "parent",
    "title",
    "rubric",
    "misconceptions",
    "canonical_explanation",
    "example",
    "source_refs",
)


class Curriculum:
    def __init__(self, tree: Tree, content_hash: str | None = None):
        self.tree = tree
        self.by_id: dict[str, Node] = {n.id: n for n in tree.nodes}
        # Document order is the priority order within a level.
        self.order: dict[str, int] = {n.id: i for i, n in enumerate(tree.nodes)}
        self.content_hash = content_hash

    def node(self, node_id: str) -> Node:
        return self.by_id[node_id]

    def children(self, node_id: str) -> list[Node]:
        return [n for n in self.tree.nodes if n.parent == node_id]

    def ancestors(self, node_id: str) -> list[Node]:
        out: list[Node] = []
        cur = self.by_id[node_id].parent
        while cur:
            out.append(self.by_id[cur])
            cur = self.by_id[cur].parent
        return out

    def subtree_ids(self, node_id: str) -> list[str]:
        ids = [node_id]
        for child in self.children(node_id):
            ids.extend(self.subtree_ids(child.id))
        return ids

    def stable_json(self) -> str:
        """Byte-stable prompt serialisation excluding review and chapter metadata."""
        tree_data = self.tree.model_dump(
            include={
                **{field: ... for field in PROMPT_TREE_FIELDS},
                "nodes": {"__all__": set(PROMPT_NODE_FIELDS)},
            }
        )
        return json.dumps(tree_data, sort_keys=True, ensure_ascii=False, indent=1)


def load_curriculum(topic_id: str) -> Curriculum:
    from .content import load_pack

    pack = load_pack()
    if topic_id == pack.curriculum.tree.topic_id:
        return pack.curriculum
    raise FileNotFoundError(f"No curriculum for topic '{topic_id}' in content pack '{pack.pack_id}'")
