"""Split study material by chapter and section, packing whole blocks into chunks."""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from .blocks import Block, SourceLine, passage_text, split_blocks

if TYPE_CHECKING:
    from .pipeline import SplitContext
    from ..contracts.content import Passage, SourceDoc

MAX_WORDS = 350
_CHAPTER = re.compile(r"Chapter\s+(\d+)")


def split_study_material(doc: SourceDoc, text: str, context: SplitContext) -> list[Passage]:
    from ..contracts.content import Passage

    passages: list[Passage] = []
    chapter_number = 0
    chapter_count = 0
    chapter = ""
    section_number = 0
    section = ""
    section_chunk = 0
    chunk_lines: list[SourceLine] = []
    skipped_blocks = 0
    oversized = 0

    def finish_chunk() -> None:
        nonlocal chunk_lines, section_chunk
        if not chunk_lines or chapter_number == 0:
            return
        section_chunk += 1
        passage_id = f"{doc.doc_code}.ch{chapter_number}.s{section_number}.p{section_chunk}"
        passage_text_value = passage_text(chunk_lines)
        passages.append(
            Passage(
                passage_id=passage_id,
                doc_id=doc.doc_id,
                doc_type=doc.doc_type,
                paper=context.paper,
                chapter=chapter,
                section=section,
                locator=f"ch{chapter_number}.s{section_number}.p{section_chunk}",
                attempt=doc.attempt or context.attempt,
                version=doc.version,
                page=chunk_lines[0].page,
                text=passage_text_value,
                sha256=hashlib.sha256(passage_text_value.encode("utf-8")).hexdigest(),
            )
        )
        chunk_lines = []

    for block in split_blocks(text):
        if block.heading is not None:
            level, heading_text = block.heading
            if level == 1:
                finish_chunk()
                chapter_count += 1
                match = _CHAPTER.search(heading_text)
                chapter_number = int(match.group(1)) if match else chapter_count
                chapter = heading_text
                section_number = 0
                section = ""
                section_chunk = 0
            elif level == 2 and chapter_number:
                finish_chunk()
                section_number += 1
                section = heading_text
                section_chunk = 0
            elif chapter_number:
                block_lines = list(block.lines)
            else:
                skipped_blocks += 1
                continue
            if level <= 2:
                continue
            if chapter_number:
                block = Block(tuple(block_lines))
            else:
                continue
        elif chapter_number == 0:
            skipped_blocks += 1
            continue

        block_word_count = len(block.text.split())
        chunk_word_count = len(passage_text(chunk_lines).split())
        if chunk_lines and chunk_word_count + block_word_count > MAX_WORDS:
            finish_chunk()
        if block_word_count > MAX_WORDS:
            oversized += 1
        chunk_lines.extend(block.lines)
    finish_chunk()

    if skipped_blocks:
        context.warnings.append(
            f"{doc.doc_id}: skipped {skipped_blocks} preamble block(s) before the first chapter."
        )
    if oversized:
        context.warnings.append(
            f"{doc.doc_id}: {oversized} block(s) exceed {MAX_WORDS} words and were kept intact."
        )
    return passages
