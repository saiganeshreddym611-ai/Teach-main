"""API-facing contract schemas for future versioned endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Phase = Literal["DIAGNOSTIC", "INSTRUCT", "TEACH_BACK", "COMPLETE", "TASK", "REVIEW"]


class CreateSessionRequest(BaseModel):
    student_id: str = "demo_student"
    topic_id: str = "ind_as_115"


class CreateSessionResponse(BaseModel):
    session_id: str
    phase: Phase
    opening_prompt: str


class TurnRequest(BaseModel):
    transcript: str = Field(min_length=1)


class SessionView(BaseModel):
    session_id: str
    student_id: str
    topic_id: str
    phase: Phase
    target_node: str | None = None
    student_level_summary: str = ""
    mastery: list[dict] = Field(default_factory=list)
    turns: list[dict] = Field(default_factory=list)
    ledger: list[dict] = Field(default_factory=list)
