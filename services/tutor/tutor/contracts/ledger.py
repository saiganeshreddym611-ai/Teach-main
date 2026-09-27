"""Schemas for cited, append-only student ledger events."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from tutor.models import LedgerEvent, LedgerSource, _now, _uid

from .content import Sha256


class RubricItemResult(BaseModel):
    rubric_id: str
    score: float = Field(ge=0.0, le=1.0)
    node_id: str | None = None
    passage_ids: list[str] = []


class TaskAttemptEvent(BaseModel):
    kind: Literal["task"] = "task"
    id: str = Field(default_factory=_uid)
    student_id: str
    session_id: str
    skill_id: str
    task_id: str
    template_version: str
    variant_seed: int
    answer_key_sha256: Sha256
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    item_results: list[RubricItemResult] = []
    evidence_turn_id: str
    grader_call_id: str | None = None
    ts: datetime = Field(default_factory=_now)
