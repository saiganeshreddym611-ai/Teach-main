"""Schemas for claim extraction and citation-backed grading."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from tutor.models import NodeStatus

from .content import Citation


class ClaimJudgment(str, Enum):
    ACCURATE = "ACCURATE"
    INACCURATE = "INACCURATE"
    MISCONCEPTION = "MISCONCEPTION"
    UNSUPPORTED = "UNSUPPORTED"
    OFF_SYLLABUS = "OFF_SYLLABUS"


class Claim(BaseModel):
    claim_id: str
    quote: str
    node_id: str | None = None
    judgment: ClaimJudgment
    passage_ids: list[str] = []


class NodeVerdictV2(BaseModel):
    node_id: str
    status: NodeStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    rubric_items_met: list[int] = []
    misconception_ids: list[int] = []
    passage_ids: list[str] = []
    citation_origin: Literal["model", "node_link"] = "node_link"


class GraderOutput(BaseModel):
    claims: list[Claim] = []
    verdicts: list[NodeVerdictV2]
    summary: str


class Omission(BaseModel):
    node_id: str
    citations: list[Citation] = []
