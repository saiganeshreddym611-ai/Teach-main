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


class ChoiceCheck(BaseModel):
    """A drill answered by picking one of the task's `options`."""
    type: Literal["choice"]
    field: str
    correct: str


RubricCheck = Annotated[
    NumericCheck | DiscrepancyCheck | JudgementCheck | ChoiceCheck,
    Field(discriminator="type"),
]


class Mistake(BaseModel):
    """A predictable wrong answer and the feedback that teaches the point it misses.

    Numeric drills give `expr`, the wrong answer as an expression of the params (`tutor.skills.expr`);
    choice drills give the wrong `choice`.
    """
    field: str
    expr: str = ""
    choice: str = ""
    feedback: str


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
    kind: Literal["calculation", "discrepancy_hunt", "drill"]
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
    # Drills (T55): short, one-answer tasks with instant feedback.
    options: list[str] = []            # choice drills, shown in this order
    answer_exprs: dict[str, str] = {}  # calculator "formula": each answer field as an expression of the params
    explanation: str = ""              # teaching shown after any answer, with the paragraph
    mistakes: list[Mistake] = []
    example_params: dict[str, str] = {}  # one valid parameter set, for briefs and tests


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
    # "micro": one idea, practised with drills; "capstone": a whole case, opened after its `requires`.
    level: Literal["micro", "capstone"] = "capstone"
    node_ids: list[str] = []
    requires: list[str] = []
