"""Schemas for versioned syllabus content and review evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ReviewStatus = Literal["draft", "claude_reviewed", "needs_expert", "signed_off"]
DocType = Literal["standard", "study_material", "rtp", "mtp", "past_paper", "amendment"]
ClaimVerdict = Literal["supported", "contradicted", "not_found"]
USABLE_REVIEW_STATUSES: frozenset[str] = frozenset({"claude_reviewed", "signed_off"})


class ReviewerInfo(BaseModel):
    mode: Literal["session", "claude-api"]
    model: str = ""


class ReviewClaim(BaseModel):
    claim: str
    verdict: ClaimVerdict
    passage_id: str | None = None
    quote: str = ""
    quote_verified: bool = False


class ReviewMeta(BaseModel):
    status: ReviewStatus = "draft"
    content_sha256: Sha256
    reviewer: ReviewerInfo | None = None
    claims: list[ReviewClaim] = []
    report_id: str | None = None
    signed_off_by: str | None = None
    signed_off_at: datetime | None = None
    notes: str = ""


class ReleaseSignoff(BaseModel):
    pack_id: str
    version: str
    content_hash: Sha256
    signed_off_by: str
    signed_off_at: datetime
    scope_note: str = ""


class SourceDoc(BaseModel):
    doc_id: str
    doc_code: str
    title: str
    short_name: str = ""
    doc_type: DocType
    issuer: str = ""
    authority_rank: int = Field(ge=1)
    attempt: str | None = None
    version: str = ""
    path: str
    sha256: str = ""
    license_note: str = ""


class Passage(BaseModel):
    passage_id: str
    doc_id: str
    doc_type: DocType
    paper: str = ""
    chapter: str = ""
    section: str = ""
    locator: str
    attempt: str | None = None
    version: str = ""
    page: int | None = None
    text: str
    sha256: Sha256
    supersedes: list[str] = []


class Citation(BaseModel):
    passage_id: str
    label: str
    doc_id: str


class ScoredPassage(BaseModel):
    passage: Passage
    score: float
    confidence: float = Field(ge=0.0, le=1.0)


class PackManifest(BaseModel):
    pack_id: str
    exam: str
    paper: str
    attempt: str
    version: str
    topics: list[str]
    doc_codes: dict[str, str] = {}
    out_of_scope_message: str = ""


class CorpusManifest(BaseModel):
    built_from: dict[str, str]
    chunk_count: int = Field(ge=0)
    corpus_sha256: Sha256
