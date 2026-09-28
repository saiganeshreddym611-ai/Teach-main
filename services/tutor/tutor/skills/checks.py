"""Content checks for skills and task templates (run by `scripts/validate_pack.py`).

The Pydantic contracts check structure at load time; these are the cross-reference and
arithmetic checks a schema cannot express.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from ..content import ContentPack
from ..contracts.skills import DiscrepancyCheck, NumericCheck, SkillDef, TaskTemplate
from ..retrieval.corpus import Corpus
from .expr import ExprError, names
from .registry import CALCULATOR_NAMES

# "1000" (absolute), "0.5%" (relative), or "0.5%|1000" (the larger of the two, HUMAN-DECISIONS 7.3).
TOLERANCE = re.compile(r"^(?:\d+(?:\.\d+)?%(?:\|\d+(?:\.\d+)?)?|\d+(?:\.\d+)?)$")
WEIGHT_EPSILON = 1e-9


@dataclass
class CheckReport:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_skills(
    pack: ContentPack, skills: dict[str, SkillDef], tasks: dict[str, TaskTemplate], corpus: Corpus | None
) -> CheckReport:
    report = CheckReport()
    for skill in skills.values():
        for task_id in skill.task_ids:
            task = tasks.get(task_id)
            if task is None:
                report.failures.append(f"skill {skill.skill_id}: task '{task_id}' does not exist")
            elif task.skill_id != skill.skill_id:
                report.failures.append(f"skill {skill.skill_id}: task '{task_id}' belongs to '{task.skill_id}'")
    listed = {task_id for skill in skills.values() for task_id in skill.task_ids}
    for task in tasks.values():
        if task.task_id not in listed:
            report.failures.append(f"task {task.task_id}: no skill lists it")
        report.failures.extend(f"task {task.task_id}: {problem}" for problem in _task_problems(pack, task, corpus))
    if corpus is None and tasks:
        report.warnings.append(f"{pack.pack_id} has no corpus yet: passage IDs in tasks were not checked")
    return report


def _task_problems(pack: ContentPack, task: TaskTemplate, corpus: Corpus | None) -> list[str]:
    problems: list[str] = []
    known = pack.curriculum.by_id
    node_refs = [("node_ids", n) for n in task.node_ids]
    node_refs += [(f"rubric {r.id}", r.node_id) for r in task.rubric]
    node_refs += [(f"discrepancy {d.id}", d.node_id) for d in task.planted_discrepancies]
    problems += [f"{where}: node '{nid}' is not in the concept map" for where, nid in node_refs if nid not in known]

    if corpus is not None:
        passage_refs = [(f"rubric {r.id}", p) for r in task.rubric for p in r.passage_ids]
        passage_refs += [(f"discrepancy {d.id}", p) for d in task.planted_discrepancies for p in d.passage_ids]
        problems += [f"{where}: passage '{pid}' is not in the corpus" for where, pid in passage_refs if pid not in corpus.by_id]

    if task.calculator not in CALCULATOR_NAMES:
        problems.append(f"calculator '{task.calculator}' is not registered")

    total = sum(r.weight for r in task.rubric)
    if abs(total - 1.0) > WEIGHT_EPSILON:
        problems.append(f"rubric weights sum to {total:g}, not 1.0")
    if not any(r.required for r in task.rubric):
        problems.append("no required rubric item (the key treatment decision must be required)")
    ids = [r.id for r in task.rubric]
    problems += [f"rubric id '{i}' is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]

    planted = {d.id for d in task.planted_discrepancies}
    for item in task.rubric:
        check = item.check
        if isinstance(check, NumericCheck):
            if check.field not in task.answer_fields:
                problems.append(f"rubric {item.id}: field '{check.field}' is not an answer field")
            if not TOLERANCE.match(check.tolerance):
                problems.append(f"rubric {item.id}: tolerance '{check.tolerance}' is not '1000', '0.5%' or '0.5%|1000'")
        elif isinstance(check, DiscrepancyCheck) and check.discrepancy_id not in planted:
            problems.append(f"rubric {item.id}: discrepancy '{check.discrepancy_id}' is not planted")

    rows = {row.get("row_id") for doc in task.documents for row in doc.rows}
    for disc in task.planted_discrepancies:
        if disc.row_id not in rows:
            problems.append(f"discrepancy {disc.id}: row '{disc.row_id}' is not in any document")
    for doc in task.documents:
        for i, row in enumerate(doc.rows, start=1):
            if "row_id" not in row:
                problems.append(f"document {doc.doc_id}: row {i} has no row_id")
            extra = sorted(set(row) - set(doc.columns) - {"row_id"})
            if extra:
                problems.append(f"document {doc.doc_id}: row {row.get('row_id', i)} has undeclared columns {', '.join(extra)}")
    if task.kind == "discrepancy_hunt" and not task.planted_discrepancies:
        problems.append("a discrepancy hunt has no planted discrepancies")

    fillable = set(task.params) | set(task.company)
    texts = [("narrative", task.narrative_template)]
    texts += [(f"document {d.doc_id} title", d.title) for d in task.documents]
    texts += [(f"document {d.doc_id}", cell) for d in task.documents for row in d.rows for cell in row.values()]
    for where, text in texts:
        problems += [f"{where}: {p}" for p in _placeholder_problems(text, fillable)]
    answer_fillable = fillable | set(task.answer_fields)
    problems += [f"model answer: {p}" for p in _placeholder_problems(task.model_answer_template, answer_fillable)]

    for constraint in task.constraints:
        try:
            unknown = names(constraint) - set(task.params)
        except ExprError as exc:
            problems.append(f"constraint '{constraint}': {exc}")
            continue
        if unknown:
            problems.append(f"constraint '{constraint}': unknown parameter {', '.join(sorted(unknown))}")
    return problems


def _placeholder_problems(text: str, allowed: set[str]) -> list[str]:
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(text) if f is not None]
    except ValueError as exc:
        return [f"bad placeholder syntax ({exc})"]
    problems = []
    for name in fields:
        if not name.isidentifier():
            problems.append(f"placeholder '{{{name}}}' must be a plain name")
        elif name not in allowed:
            problems.append(f"placeholder '{{{name}}}' has no parameter")
    return problems
