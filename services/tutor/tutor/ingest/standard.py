"""Split numbered standards and amendments into paragraph passages."""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from .blocks import Block, SourceLine, passage_text, split_blocks

if TYPE_CHECKING:
    from .pipeline import SplitContext
    from ..contracts.content import Passage, SourceDoc

_PARAGRAPH = re.compile(r"^(?P<num>(?:IE|B|C)?\d{1,3}[A-Z]{0,2})\.?\s+\S")


def _passage(
    doc: SourceDoc,
    context: SplitContext,
    number: str,
    section: str,
    lines: list[SourceLine],
    supersedes: list[str] | None = None,
) -> Passage:
    from ..contracts.content import Passage

    text = passage_text(lines)
    return Passage(
        passage_id=f"{doc.doc_code}.para.{number}",
        doc_id=doc.doc_id,
        doc_type=doc.doc_type,
        paper=context.paper,
        chapter="",
        section=section,
        locator=f"para.{number}",
        attempt=doc.attempt or context.attempt,
        version=doc.version,
        page=lines[0].page if lines else None,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        supersedes=supersedes or [],
    )


def _split_standard(
    doc: SourceDoc, text: str, context: SplitContext, *, amendment: bool
) -> list[Passage]:
    passages = []
    number: str | None = None
    section = ""
    paragraph_lines: list[SourceLine] = []
    skipped_blocks = 0

    def finish() -> None:
        nonlocal number, paragraph_lines
        if number is None:
            return
        clean_lines = []
        supersedes = []
        for line in paragraph_lines:
            if amendment and line.text.startswith("Supersedes:"):
                supersedes.extend(
                    passage_id.strip()
                    for passage_id in line.text.partition(":")[2].split(",")
                    if passage_id.strip()
                )
            else:
                clean_lines.append(line)
        passages.append(_passage(doc, context, number, section, clean_lines, supersedes))
        number = None
        paragraph_lines = []

    for block in split_blocks(text):
        if block.heading is not None:
            finish()
            section = block.heading[1]
            continue
        match = _PARAGRAPH.match(block.lines[0].text)
        if match:
            finish()
            number = match.group("num")
            paragraph_lines = list(block.lines)
        elif number is None:
            skipped_blocks += 1
        else:
            paragraph_lines.extend(block.lines)
    finish()

    if skipped_blocks:
        kind = "amendment" if amendment else "standard"
        context.warnings.append(
            f"{doc.doc_id}: skipped {skipped_blocks} unnumbered block(s) outside a paragraph ({kind})."
        )
    return passages


def split_standard(doc: SourceDoc, text: str, context: SplitContext) -> list[Passage]:
    return _split_standard(doc, text, context, amendment=False)


def split_amendment(doc: SourceDoc, text: str, context: SplitContext) -> list[Passage]:
    return _split_standard(doc, text, context, amendment=True)
