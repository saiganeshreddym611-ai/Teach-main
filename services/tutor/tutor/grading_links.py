"""Passages linked to each concept node, for grounded grading.

The grader may cite only passages linked to a node through its `source_refs` (T21/T22 `for_node`).
Similarity search never enters grading: these links are fixed by the content pack.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .content import load_pack
from .contracts.content import Citation, Passage
from .curriculum import Curriculum
from .retrieval import Corpus, cite_passage, get_retriever

# Above this many (estimated) tokens, teach-back calls send only the focus node's passages.
PASSAGES_BLOCK_TOKEN_LIMIT = 30_000


@dataclass
class NodeLinks:
    """node_id -> linked passages in document order. Empty when the pack has no corpus."""

    passages: dict[str, list[Passage]] = field(default_factory=dict)
    corpus: Corpus | None = None

    def ids(self, node_id: str) -> list[str]:
        return [p.passage_id for p in self.passages.get(node_id, [])]

    def all_ids(self) -> set[str]:
        return {p.passage_id for ps in self.passages.values() for p in ps}

    def citations(self, node_id: str, limit: int = 3) -> list[Citation]:
        if self.corpus is None:
            return []
        return [cite_passage(p, self.corpus) for p in self.passages.get(node_id, [])[:limit]]


def node_links(curriculum: Curriculum) -> NodeLinks:
    """Links for the active pack's curriculum; empty for any other curriculum or without a corpus."""
    pack = load_pack()
    if pack.curriculum.tree.topic_id != curriculum.tree.topic_id:
        return NodeLinks()
    retriever = get_retriever(pack)
    if retriever is None:
        return NodeLinks()
    return NodeLinks({n.id: retriever.for_node(n.id) for n in curriculum.tree.nodes}, retriever.corpus)


def _unique_ids(links: NodeLinks, node_ids: list[str]) -> list[str]:
    """Linked passage IDs of these nodes, in node order then document order, each once."""
    return list(dict.fromkeys(pid for node_id in node_ids for pid in links.ids(node_id)))


def _render(links: NodeLinks, passage_ids: list[str]) -> str:
    by_id = {p.passage_id: p for ps in links.passages.values() for p in ps}
    return "\n".join(f'<passage id="{pid}">\n{by_id[pid].text}\n</passage>' for pid in passage_ids)


def offered_passage_ids(curriculum: Curriculum, links: NodeLinks, focus_node_id: str | None = None) -> list[str]:
    """The passage IDs `passages_block` sends, in its order: every linked passage, or only the focus
    node's when the full block exceeds PASSAGES_BLOCK_TOKEN_LIMIT on a teach-back."""
    ids = _unique_ids(links, [n.id for n in curriculum.tree.nodes])
    if focus_node_id and estimate_tokens(_render(links, ids)) > PASSAGES_BLOCK_TOKEN_LIMIT:
        ids = _unique_ids(links, [focus_node_id])
    return ids


def estimate_tokens(text: str) -> int:
    """Rough size for the cache-size decision: about 4 characters per token."""
    return len(text) // 4


def passages_block(curriculum: Curriculum, links: NodeLinks, focus_node_id: str | None = None) -> dict | None:
    """Cached system block with every linked passage, in node order then document order, each once.

    Returns None when there are no passages. When the full block exceeds
    PASSAGES_BLOCK_TOKEN_LIMIT and a focus node is given (teach-back), only that node's passages
    are sent.
    """
    ids = offered_passage_ids(curriculum, links, focus_node_id)
    if not ids:
        return None
    body = _render(links, ids)
    text = f"<source_passages>\n{body}\n</source_passages>"
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}
