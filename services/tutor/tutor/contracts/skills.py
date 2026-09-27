"""Schemas for authored, deterministic skill tasks."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ParamSpec(BaseModel):
    type: Literal["money", "percent", "date", "int", "choice", "name"]
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] = Field(default_factory=list)


class SkillDef(BaseModel):
    skill_id: str
    title: str
    description: str
    task_ids: list[str]
    unlock_rule: Literal["all_tasks_passed"] = "all_tasks_passed"


class TaskRubricItem(BaseModel):
    rubric_id: str
    description: str
    node_id: str
    passage_ids: list[str] = Field(default_factory=list)


class TaskTemplate(BaseModel):
    task_id: str
    skill_id: str
    title: str
    description: str
    template_version: str
    parameters: dict[str, ParamSpec] = Field(default_factory=dict)
    rubric: list[TaskRubricItem] = Field(default_factory=list)
    brief: dict[str, Any] = Field(default_factory=dict)
    review_status: Literal["draft", "claude_reviewed", "needs_expert", "signed_off"] = "draft"
