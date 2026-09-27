"""Schemas for claim extraction and citation-backed grading."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ClaimJudgment = Literal[
    "ACCURATE",
    "INACCURATE",
    "MISCONCEPTION",
    "UNSUPPORTED",
    "OFF_SYLLABUS",
]


class Claim(BaseModel):
    claim_id: str
    quote: str
    node_id: str | None = None
    judgment: ClaimJudgment
    passage_ids: list[str] = Field(default_factory=list)


class NodeVerdictV2(BaseModel):
    node_id: str
    status: Literal["NOT_MENTIONED", "GAP", "PARTIAL", "VERIFIED"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    rubric_items_met: list[int] = Field(default_factory=list)
    misconception_ids: list[int] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    citation_origin: Literal["model", "node_link"] = "node_link"


class GraderOutput(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    verdicts: list[NodeVerdictV2] = Field(default_factory=list)
    summary: str


class Omission(BaseModel):
    node_id: str
    citations: list[str] = Field(default_factory=list)
