"""Schemas for cited, append-only student ledger events."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LedgerEvent(BaseModel):
    kind: Literal["concept"] = "concept"
    id: str
    student_id: str
    session_id: str | None = None
    node_id: str
    status: Literal["NOT_MENTIONED", "GAP", "PARTIAL", "VERIFIED"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    evidence_turn_id: str
    passage_ids: list[str] = Field(default_factory=list)
    grader_call_id: str | None = None
    content_version: str | None = None
    source: Literal["diagnostic", "probe", "teach_back", "task", "review", "practice"]
    phase: Literal["DIAGNOSTIC", "INSTRUCT", "TEACH_BACK", "COMPLETE"]
    ts: datetime


class TaskItemResult(BaseModel):
    rubric_id: str
    score: float = Field(ge=0.0)
    node_id: str | None = None
    passage_ids: list[str] = Field(default_factory=list)


class TaskAttemptEvent(BaseModel):
    kind: Literal["task"] = "task"
    id: str
    student_id: str
    session_id: str
    skill_id: str
    task_id: str
    template_version: str
    variant_seed: int
    answer_key_sha256: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    item_results: list[TaskItemResult] = Field(default_factory=list)
    evidence_turn_id: str
    grader_call_id: str | None = None
    ts: datetime
