"""API-facing contract schemas for future versioned endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .content import Citation, PackManifest, Passage, Sha256, SourceDoc


class ContentInfo(BaseModel):
    manifest: PackManifest
    content_hash: Sha256
    review_counts: dict[str, dict[str, int]] = {}
    # The active topic, so clients never hard-code it (T25).
    topic_id: str = ""
    standard: str = ""


class PassageResponse(BaseModel):
    passage: Passage
    source: SourceDoc
    citation: Citation


class VerifyRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    audio_b64: str = Field(min_length=1, max_length=7_000_000)


class VerifyResponse(BaseModel):
    match: bool
    score: float = Field(ge=0.0, le=1.0)
    method: str
