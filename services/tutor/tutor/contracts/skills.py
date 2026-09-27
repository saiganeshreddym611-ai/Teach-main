"""Schemas for authored, deterministic skill tasks."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .content import Sha256

ParamType = Literal["money", "percent", "date", "int", "choice", "name"]


class ParamSpec(BaseModel):
    type: ParamType
    min: str | None = None
    max: str | None = None
    step: str | None = None
    choices: list[str] = []


class NumericCheck(BaseModel):
    type: Literal["numeric"]
    field: str
    tolerance: str = "0"


class DiscrepancyCheck(BaseModel):
    type: Literal["discrepancy"]
    discrepancy_id: str


class JudgementCheck(BaseModel):
    type: Literal["judgement"]


RubricCheck = Annotated[
    NumericCheck | DiscrepancyCheck | JudgementCheck,
    Field(discriminator="type"),
]


class RubricItem(BaseModel):
    id: str
    text: str
    weight: float = Field(default=1.0, gt=0.0)
    node_id: str
    passage_ids: list[str] = []
    required: bool = False
    check: RubricCheck


class PlantedDiscrepancy(BaseModel):
    id: str
    row_id: str
    issue_type: str = Field(pattern=r"^[a-z_]+$")
    node_id: str
    passage_ids: list[str] = []


class TaskDocument(BaseModel):
    doc_id: str
    title: str
    columns: list[str]
    rows: list[dict[str, str]]


class TaskTemplate(BaseModel):
    task_id: str
    skill_id: str
    title: str
    kind: Literal["calculation", "discrepancy_hunt"]
    node_ids: list[str]
    company: dict[str, str] = {}
    narrative_template: str
    params: dict[str, ParamSpec] = {}
    constraints: list[str] = []
    documents: list[TaskDocument] = []
    calculator: str
    answer_fields: list[str]
    rubric: list[RubricItem]
    planted_discrepancies: list[PlantedDiscrepancy] = []
    model_answer_template: str = ""
    pass_threshold: float = Field(ge=0.0, le=1.0)
    template_version: str


class TaskVariant(BaseModel):
    task_id: str
    seed: int
    params: dict[str, str]
    narrative: str
    documents: list[TaskDocument] = []
    answer_key: dict[str, str]
    answer_key_sha256: Sha256


class SkillDef(BaseModel):
    skill_id: str
    title: str
    description: str = ""
    task_ids: list[str]
    unlock_rule: Literal["all_tasks_passed"] = "all_tasks_passed"
