"""Split revision and exam documents into question and answer passages."""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from .blocks import SourceLine, passage_text, split_blocks
from .errors import IngestError

if TYPE_CHECKING:
    from .pipeline import SplitContext
    from ..contracts.content import Passage, SourceDoc

_QUESTION = re.compile(r"^(?:Question|QUESTION|Q(?=\s*\d))\s*(?P<n>\d+)\s*[.:)]?(?:\s+|$)")
_ANSWER = re.compile(r"^(?:Answer|ANSWER|Ans\.|A(?=\d))\s*(?P<n>\d+)?\s*[.:)]?(?:\s+|$)")


def split_qa(doc: SourceDoc, text: str, context: SplitContext) -> list[Passage]:
    from ..contracts.content import Passage

    passages: list[Passage] = []
    number: str | None = None
    part: str | None = None
    passage_lines: list[SourceLine] = []

    def finish() -> None:
        nonlocal passage_lines
        if number is None or part is None or not passage_lines:
            passage_lines = []
            return
        locator = f"q{number}" + (".ans" if part == "answer" else "")
        passage_text_value = passage_text(passage_lines)
        passages.append(
            Passage(
                passage_id=f"{doc.doc_code}.{locator}",
                doc_id=doc.doc_id,
                doc_type=doc.doc_type,
                paper=context.paper,
                chapter="",
                section=f"Q{number}",
                locator=locator,
                attempt=doc.attempt or context.attempt,
                version=doc.version,
                page=passage_lines[0].page,
                text=passage_text_value,
                sha256=hashlib.sha256(passage_text_value.encode("utf-8")).hexdigest(),
            )
        )
        passage_lines = []

    for block in split_blocks(text):
        marker_line = block.lines[0].text
        question_match = _QUESTION.match(marker_line)
        answer_match = _ANSWER.match(marker_line)
        if question_match:
            finish()
            number = question_match.group("n")
            part = "question"
            passage_lines = list(block.lines)
        elif answer_match:
            finish()
            answer_number = answer_match.group("n")
            if answer_number:
                number = answer_number
            elif number is None:
                raise IngestError(f"{doc.doc_id}: answer appears before any question")
            part = "answer"
            passage_lines = list(block.lines)
        elif number is not None and part is not None:
            passage_lines.extend(block.lines)
    finish()
    return passages
