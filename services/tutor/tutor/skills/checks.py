"""Content checks for skills and task templates (run by `scripts/validate_pack.py`).

The Pydantic contracts check structure at load time; these are the cross-reference and
arithmetic checks a schema cannot express.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from decimal import Decimal, InvalidOperation

from ..content import ContentPack
from ..contracts.jobs import JobProfile
from ..contracts.skills import ChoiceCheck, DiscrepancyCheck, NumericCheck, SkillDef, TaskTemplate
from ..retrieval.corpus import Corpus
from .drills import formula_answers, mistake_value, numeric_check, within
from .expr import ExprError, evaluate, names
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
        report.failures.extend(f"skill {skill.skill_id}: {p}" for p in _skill_problems(pack, skill, skills, tasks))
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


def check_jobs(jobs: dict[str, JobProfile], skills: dict[str, SkillDef]) -> list[str]:
    return [f"job {job.job_id}: skill '{s}' does not exist" for job in jobs.values() for s in job.skills if s not in skills]


def _skill_problems(
    pack: ContentPack, skill: SkillDef, skills: dict[str, SkillDef], tasks: dict[str, TaskTemplate]
) -> list[str]:
    problems = [f"node '{n}' is not in the concept map" for n in skill.node_ids if n not in pack.curriculum.by_id]
    problems += [f"requires '{r}', which does not exist" for r in skill.requires if r not in skills]
    if _in_cycle(skill.skill_id, skills):
        problems.append("its requires chain loops back to itself")
    if skill.level == "micro" and not skill.node_ids:
        problems.append("a micro skill names the concept nodes it practises (node_ids)")
    for task_id in skill.task_ids:
        task = tasks.get(task_id)
        if task is not None and (task.kind == "drill") != (skill.level == "micro"):
            problems.append(f"task '{task_id}' is a {task.kind}; micro skills hold drills and capstones hold the rest")
    return problems


def _in_cycle(start: str, skills: dict[str, SkillDef]) -> bool:
    seen: set[str] = set()
    stack = list(skills[start].requires)
    while stack:
        current = stack.pop()
        if current == start:
            return True
        if current in seen or current not in skills:
            continue
        seen.add(current)
        stack.extend(skills[current].requires)
    return False


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
    if task.example_params:
        problems += _example_problems(task)
    if task.kind == "drill":
        problems += _drill_problems(task, answer_fillable)
    elif task.options or task.answer_exprs or task.mistakes or any(isinstance(r.check, ChoiceCheck) for r in task.rubric):
        problems.append("options, answer_exprs, mistakes and choice checks belong to drills only")
    return problems


def _example_problems(task: TaskTemplate) -> list[str]:
    """The worked example must be a variant the generator could produce."""
    if set(task.example_params) != set(task.params):
        return ["example_params must give exactly the task's params"]
    problems = []
    for name, value in task.example_params.items():
        spec = task.params[name]
        if spec.choices:
            if value not in spec.choices:
                problems.append(f"example {name}='{value}' is not one of its choices")
            continue
        try:
            number = Decimal(value)
        except InvalidOperation:
            problems.append(f"example {name}='{value}' is not a number")
            continue
        if (spec.min is not None and number < Decimal(spec.min)) or (spec.max is not None and number > Decimal(spec.max)):
            problems.append(f"example {name}={value} is outside {spec.min} to {spec.max}")
    for constraint in task.constraints:
        try:
            if evaluate(constraint, task.example_params) is not True:
                problems.append(f"example breaks constraint '{constraint}'")
        except ExprError:
            pass  # reported by the constraint check
    return problems


def _drill_problems(task: TaskTemplate, fillable: set[str]) -> list[str]:
    problems = []
    if len(task.rubric) != 1 or not task.rubric[0].required:
        problems.append("a drill has exactly one rubric item, and it is required")
    if not task.explanation.strip():
        problems.append("a drill needs an explanation (the teaching shown after the answer)")
    if task.params and not task.example_params:
        problems.append("a drill with params needs example_params")
    texts = [("explanation", task.explanation)] + [(f"mistake {i}", m.feedback) for i, m in enumerate(task.mistakes, start=1)]
    for where, text in texts:
        problems += [f"{where}: {p}" for p in _placeholder_problems(text, fillable)]

    choice = next((r.check for r in task.rubric if isinstance(r.check, ChoiceCheck)), None)
    if task.calculator == "choice":
        if choice is None or len(task.options) < 2:
            problems.append("a choice drill needs a choice check and at least two options")
            return problems
        if choice.correct not in task.options:
            problems.append(f"correct answer '{choice.correct}' is not one of the options")
        for i, m in enumerate(task.mistakes, start=1):
            if m.choice not in task.options or m.choice == choice.correct:
                problems.append(f"mistake {i}: '{m.choice}' must be a wrong option")
        return problems

    if set(task.answer_exprs) != set(task.answer_fields):
        problems.append("answer_exprs must give exactly the answer fields")
    for name, expr in task.answer_exprs.items():
        try:
            unknown = names(expr) - set(task.params)
        except ExprError as exc:
            problems.append(f"answer '{name}': {exc}")
            continue
        if unknown:
            problems.append(f"answer '{name}': unknown parameter {', '.join(sorted(unknown))}")
    if problems or not task.example_params:
        return problems
    try:
        answers = formula_answers(task, task.example_params)
    except ExprError as exc:
        return [f"answer on the example: {exc}"]
    for i, m in enumerate(task.mistakes, start=1):
        check = numeric_check(task, m.field)
        if check is None:
            problems.append(f"mistake {i}: '{m.field}' is not a numeric answer field")
            continue
        try:
            wrong = mistake_value(m, task.example_params)
        except ExprError as exc:
            problems.append(f"mistake {i}: {exc}")
            continue
        if within(wrong, answers[m.field], check.tolerance):
            problems.append(f"mistake {i}: on the example it gives the right answer, so it cannot be told apart")
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
