"""Shared text-line and block handling for source splitters."""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(?P<marks>#{1,}) (?P<text>.*)$")


@dataclass(frozen=True)
class SourceLine:
    text: str
    page: int | None


@dataclass(frozen=True)
class Block:
    lines: tuple[SourceLine, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text.rstrip() for line in self.lines if line.text.strip()).strip()

    @property
    def first_page(self) -> int | None:
        return self.lines[0].page if self.lines else None

    @property
    def heading(self) -> tuple[int, str] | None:
        if len(self.lines) != 1:
            return None
        match = _HEADING.match(self.lines[0].text)
        if not match:
            return None
        return len(match.group("marks")), match.group("text").rstrip()


def iter_lines(text: str) -> list[SourceLine]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    has_pages = "\f" in normalized
    page = 1
    result: list[SourceLine] = []
    for raw_line in normalized.split("\n"):
        segments = raw_line.split("\f")
        for index, segment in enumerate(segments):
            result.append(SourceLine(segment, page if has_pages else None))
            if index < len(segments) - 1:
                page += 1
    return result


def split_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    current: list[SourceLine] = []

    def flush() -> None:
        if current:
            blocks.append(Block(tuple(current)))
            current.clear()

    for line in iter_lines(text):
        if not line.text.strip():
            flush()
            continue
        heading_match = _HEADING.match(line.text)
        if heading_match:
            flush()
            blocks.append(Block((line,)))
            continue
        current.append(line)
    flush()
    return blocks


def passage_text(lines: list[SourceLine] | tuple[SourceLine, ...]) -> str:
    return "\n".join(line.text.rstrip() for line in lines if line.text.strip()).strip()
