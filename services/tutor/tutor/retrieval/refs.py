from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from ..contracts.content import Citation, Passage, SourceDoc
from .corpus import Corpus

PARA = r"(?:IE|B|C)?\d{1,3}[A-Z]{0,2}"
REF_RE = re.compile(
    rf"^(?P<doc>.+?)\.para\.(?P<start>{PARA})(?:-(?P<end>{PARA}))?(?P<sub>(?:\([a-z0-9]{{1,4}}\))*)$"
)


@dataclass(frozen=True)
class SourceRef:
    raw: str
    doc_code: str
    start: str
    end: str | None
    sub: str


class UnresolvedRef(LookupError):
    def __init__(self, ref: str, reason: str) -> None:
        self.ref, self.reason = ref, reason
        super().__init__(f"{ref}: {reason}")


def parse_ref(ref: str) -> SourceRef | None:
    match = REF_RE.fullmatch(ref)
    if match is None:
        return None
    return SourceRef(ref, match["doc"], match["start"], match["end"], match["sub"])


def resolve_ref(ref: str, corpus: Corpus) -> list[Passage]:
    if ref in corpus.by_id:
        return [corpus.by_id[ref]]
    parsed = parse_ref(ref)
    if parsed is None:
        raise UnresolvedRef(ref, "no such passage")
    doc = corpus.doc_for_code(parsed.doc_code)
    if doc is None:
        raise UnresolvedRef(ref, "unknown document code")
    start_id = f"{doc.doc_code}.para.{parsed.start}"
    end_id = f"{doc.doc_code}.para.{parsed.end}" if parsed.end else start_id
    if start_id not in corpus.by_id:
        raise UnresolvedRef(ref, f"missing passage {start_id}")
    if end_id not in corpus.by_id:
        raise UnresolvedRef(ref, f"missing passage {end_id}")
    document_order = corpus.order.get(doc.doc_id, [])
    start_index = document_order.index(start_id)
    end_index = document_order.index(end_id)
    if end_index < start_index:
        raise UnresolvedRef(ref, "range is reversed")
    return [corpus.by_id[passage_id] for passage_id in document_order[start_index : end_index + 1]]


def _month(attempt: str | None) -> str:
    if not attempt or "-" not in attempt:
        return ""
    year, month = attempt.split("-", 1)
    try:
        return f"{calendar.month_name[int(month)]} {year}"
    except (ValueError, IndexError):
        return attempt


def passage_label(passage: Passage, doc: SourceDoc) -> str:
    name = doc.short_name or doc.title
    if doc.doc_type in {"standard", "amendment"}:
        locator = passage.locator.removeprefix("para.")
        return f"{name}, para {locator}"
    if doc.doc_type == "study_material":
        match = re.fullmatch(r"ch(\d+)\.s(\d+)\.p\d+", passage.locator)
        chapter = match[1] if match else passage.chapter.removeprefix("Chapter ").split(" ")[0]
        section = match[2] if match else ""
        return f"{name}, Ch {chapter}" + (f" §{section}" if section and section != "0" else "")
    locator = passage.locator
    match = re.fullmatch(r"q(\d+)(?:\.(ans))?", locator)
    if match:
        prefix = {"rtp": "RTP", "mtp": "MTP", "past_paper": "Past paper"}[doc.doc_type]
        attempt = _month(doc.attempt)
        label = f"{prefix} {attempt}, Q{match[1]}" if attempt else f"{prefix}, Q{match[1]}"
        if match[2]:
            label += " (answer)"
        return label
    return name


def ref_label(ref: str, corpus: Corpus) -> str:
    parsed = parse_ref(ref)
    passages = resolve_ref(ref, corpus)
    doc = corpus.doc(passages[0].doc_id)
    if parsed is not None and doc.doc_type in {"standard", "amendment"}:
        name = doc.short_name or doc.title
        end = parsed.end
        if end:
            return f"{name}, paras {parsed.start}–{end}{parsed.sub}"
        return f"{name}, para {parsed.start}{parsed.sub}"
    return passage_label(passages[0], doc)


def cite_passage(passage: Passage, corpus: Corpus) -> Citation:
    return Citation(passage_id=passage.passage_id, label=passage_label(passage, corpus.doc(passage.doc_id)), doc_id=passage.doc_id)


def cite_ref(ref: str, corpus: Corpus) -> Citation:
    passages = resolve_ref(ref, corpus)
    return Citation(passage_id=passages[0].passage_id, label=ref_label(ref, corpus), doc_id=passages[0].doc_id)
