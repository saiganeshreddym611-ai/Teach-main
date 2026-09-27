"""Split a concept node into single claims that can each be checked against a passage."""
from __future__ import annotations

import re

from ..models import Node
from .models import Claim

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'‘“])")
# Abbreviations that end in a full stop but do not end a sentence.
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "viz.", "cf.", "vs.", "no.", "rs.", "para.", "paras.", "ch.", "sec.")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out and out[-1].lower().endswith(_ABBREVIATIONS):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def split_node(node: Node) -> list[Claim]:
    """One claim per rubric item, explanation sentence, example sentence and misconception, in
    that order, numbered c1..cN."""
    raw: list[tuple[str, str]] = [("rubric", r) for r in node.rubric]
    raw += [("explanation", s) for s in sentences(node.canonical_explanation)]
    raw += [("example", s) for s in sentences(node.example)]
    raw += [("misconception", m) for m in node.misconceptions]
    return [
        Claim(
            claim_id=f"c{i}",
            item_id=node.id,
            kind=kind,
            text=text.strip(),
            expect="contradicted" if kind == "misconception" else "supported",
        )
        for i, (kind, text) in enumerate(((k, t) for k, t in raw if t.strip()), start=1)
    ]
