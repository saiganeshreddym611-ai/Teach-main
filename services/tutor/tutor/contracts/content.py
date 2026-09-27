"""Schemas for versioned syllabus content and review evidence."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewClaim(BaseModel):
    claim: str
    verdict: Literal["supported", "contradicted", "not_found"]
    passage_id: str | None = None
    quote: str = ""
    quote_verified: bool = False


class Reviewer(BaseModel):
    mode: Literal["session", "claude-api"]
    model: str


class ReviewMeta(BaseModel):
    status: Literal["draft", "claude_reviewed", "needs_expert", "signed_off"]
    content_sha256: str
    reviewer: Reviewer | None = None
    reviewed_at: str | None = None
    claims: list[ReviewClaim] = Field(default_factory=list)
    report_id: str | None = None
    signed_off_by: str | None = None
    signed_off_at: str | None = None
    notes: str = ""


class ReleaseSignoff(BaseModel):
    pack_id: str
    version: str
    content_hash: str
    signed_off_by: str
    signed_off_at: str
    scope_note: str = ""


class SourceDoc(BaseModel):
    doc_id: str
    doc_code: str
    title: str
    short_name: str = ""
    doc_type: Literal["standard", "study_material", "rtp", "mtp", "past_paper", "amendment"]
    issuer: str
    authority_rank: int = Field(ge=1)
    attempt: str
    version: str
    path: str
    sha256: str
    license_note: str = ""


class Passage(BaseModel):
    passage_id: str
    doc_id: str
    doc_type: Literal["standard", "study_material", "rtp", "mtp", "past_paper", "amendment"]
    paper: str
    chapter: str
    section: str
    locator: str
    attempt: str
    version: str
    page: int | None = Field(default=None, ge=1)
    text: str
    sha256: str
    supersedes: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    passage_id: str
    label: str
    doc_id: str


class ScoredPassage(BaseModel):
    passage: Passage
    score: float
    confidence: float = Field(ge=0.0, le=1.0)
