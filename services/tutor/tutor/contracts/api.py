"""API-facing contract schemas for future versioned endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .content import Citation, PackManifest, Passage, Sha256, SourceDoc
from ..models import LedgerEvent, NodeStatus


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


# --------------------------------------------------------------------------- #
# Ledger v2 export shapes (T31)
# --------------------------------------------------------------------------- #
class LedgerNodeExport(BaseModel):
    concept_id: str
    title: str
    status: Literal["MASTERED", "PARTIAL", "GAP_IDENTIFIED", "NOT_ASSESSED"]
    confidence_score: float | None = None
    last_verified: datetime | None = None  # ts of the node's latest event (pitch name kept)
    evidence_turn_id: str | None = None
    citations: list[str] = []  # citation labels of that event's passages


class StudentLedger(BaseModel):
    student_id: str
    topic_id: str
    subject: str
    standard: str
    nodes: list[LedgerNodeExport]  # every node of the curriculum, in tree order
    events: list[LedgerEvent]  # the student's raw events, all topics


class TracePassage(BaseModel):
    citation: Citation
    text: str


class LedgerTrace(BaseModel):
    event: LedgerEvent
    student_turn: str
    passages: list[TracePassage]
    grader_call_id: str | None