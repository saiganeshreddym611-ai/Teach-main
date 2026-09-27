"""Convert an MCA-notified Ind AS PDF into the text format the `standard` splitter reads (T25).

    python scripts/convert_mca_standard.py <in.pdf> <out.txt>

Uses pypdf's layout mode, which keeps words whole (plain mode splits words such as "Standa rd").
Layout facts the rules rely on, checked on Ind AS 37 (MCA, as amended to 23 March 2022):
- each page starts with a running header "Ind AS 37, Provisions, ...";
- a paragraph starts at column 0 with its number and a wide gap ("5       When another ...");
- sub-items "(a)" and continuation lines are indented;
- other column-0 lines are headings, except footnotes: at the page bottom, a column-0 line whose
  marker ("1", "2", "*") is followed by at most one space; everything after it on that page is
  footnote text;
- footnote markers also appear glued to words in the body ("1When", "Omitted*;").
The body runs from the "Objective" heading to the first "Appendix" heading; appendices restart
their own paragraph numbers, so they are left out.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from pypdf import PdfReader

HEADER = re.compile(r"^\s*Ind AS \d+[A-Z]?,")
NUM = r"(?:IE|B|C)?\d{1,3}[A-Z]{0,2}"
PARA = re.compile(rf"^(?P<num>{NUM})\.?\s{{3,}}(?P<text>\S.*)$")
FOOTNOTE = re.compile(r"^(?P<mark>\d{1,2}|\*{1,2}|#)\s?\S")
SUB_ITEM = re.compile(r"^\((?:[a-z]{1,2}|[ivx]{1,5})\)\s")
APPENDIX = re.compile(r"^Appendix\s+[A-Z0-9]\b")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _short(text: str) -> bool:
    """Could be (part of) a heading: short and without sentence punctuation at the end."""
    return 0 < len(text) < 70 and not text.endswith((".", ",", ";", ":"))


def _digit_marks(marks: set[str]) -> list[str]:
    return sorted((m for m in marks if m.isdigit()), key=len, reverse=True)


def _strip_markers(text: str, marks: set[str]) -> str:
    for mark in _digit_marks(marks):
        # "1When", "2leases": a footnote number glued to the start of a word.
        text = re.sub(rf"(?<![\w.]){mark}(?=[a-z]|[A-Z][a-z])", "", text)
        # "For the purpose of this Standard,4 an outflow": a number right after punctuation.
        text = re.sub(rf"(?<=[,;:]){mark}(?=\s)", "", text)
    return re.sub(r"\s?\*+(?=[\s;:,.)]|$)", "", text)


def _footnote_start(lines: list[str]) -> int:
    """Footnotes are the bottom run of column-0 lines on a page, from its first marker line.
    Returns len(lines) when the page has none."""
    i = len(lines)
    while i > 0 and not lines[i - 1][0].isspace() and not PARA.match(lines[i - 1]):
        i -= 1
    return next((j for j in range(i, len(lines)) if FOOTNOTE.match(lines[j])), len(lines))


def _paragraph(raw: str, marks: set[str]) -> tuple[str, str] | None:
    """(number, text) when a column-0 line starts a paragraph, with any footnote marker removed:
    "75       7A management ...", "103    11[Refer ...]", "10110  Omitted" (101 + marker 10),
    "105 13Onerous ..." (a single space after the number)."""
    if raw[0].isspace():
        return None
    match = PARA.match(raw)
    if match:
        text = match["text"]
        for mark in _digit_marks(marks):
            if re.match(rf"{mark}(?=[A-Za-z\[])", text):
                text = text[len(mark):]
                break
        return match["num"], text
    for mark in _digit_marks(marks):
        glued = re.match(rf"^(?P<num>{NUM}?){mark}\.?\s+(?P<text>\S.*)$", raw)
        spaced = re.match(rf"^(?P<num>{NUM})\.?\s+{mark}(?P<text>\S.*)$", raw)
        for found in (glued, spaced):
            if found and found["num"]:
                return found["num"], found["text"]
    return None


def convert(pdf: Path) -> str:
    out: list[str] = []
    item: list[str] | None = None  # the paragraph or sub-item being built
    heading: list[str] = []
    started = stopped = False

    def flush_item() -> None:
        nonlocal item
        if item:
            out.append(" ".join(item))
        item = None

    def flush_heading() -> None:
        if heading:
            flush_item()
            out.extend(["", f"## {' '.join(heading)}", ""])
            heading.clear()

    for page_number, page in enumerate(PdfReader(pdf).pages, start=1):
        lines = [raw for raw in (page.extract_text(extraction_mode="layout") or "").splitlines()
                 if raw.strip() and not HEADER.match(raw)]
        cut = _footnote_start(lines)
        body = lines[:cut]
        marks = {m["mark"] for m in map(FOOTNOTE.match, lines[cut:]) if m}
        page_started = False
        texts = [_squash(_strip_markers(raw, marks)) for raw in body]
        paras = [_paragraph(raw, marks) for raw in body]

        def starts_paragraph(i: int) -> bool:
            return i < len(body) and paras[i] is not None

        def heading_follows(i: int) -> bool:
            """Line i is a heading when a paragraph starts next (or after one wrapped line)."""
            return starts_paragraph(i + 1) or (i + 1 < len(body) and _short(texts[i + 1]) and starts_paragraph(i + 2))

        for i, raw in enumerate(body):
            col0 = not raw[0].isspace()
            text = texts[i]
            if not started:
                started = col0 and text == "Objective"
                continue
            if col0 and APPENDIX.match(text):
                stopped = True
                break
            if paras[i]:
                flush_heading()
                flush_item()
                if not page_started and out:
                    out.append("\f")
                page_started = True
                out.append("")
                body_text = _squash(_strip_markers(paras[i][1], marks))
                # A number with no text is a placeholder for a paragraph India left out: skip it.
                item = [f"{paras[i][0]} {body_text}"] if body_text else None
            elif heading and _short(text):
                heading.append(text)  # a heading wrapped onto a second line
            elif _short(text) and text[:1].isupper() and (col0 or heading_follows(i)):
                flush_item()
                heading.append(text)
            elif SUB_ITEM.match(text):
                flush_heading()
                flush_item()
                item = [text]
            elif item is not None and not col0:
                if item[-1].endswith("-") and text[:1].islower():
                    item[-1] += text
                else:
                    item.append(text)
            else:
                # Unnumbered prose (the objective): a block the splitter skips or attaches to the
                # paragraph before it.
                flush_heading()
                if item is None or col0:
                    flush_item()
                    out.append("")
                    item = [text]
                else:
                    item.append(text)
        if stopped:
            break
    flush_heading()
    flush_item()
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).replace("\n\n\f", "\n\f")
    return text.strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    source, target = Path(args[0]), Path(args[1])
    target.write_text(convert(source), encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
