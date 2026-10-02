"""Write a readable brief of a pack's skill tasks for the owner and expert review (T50 demo, H3).

    python scripts/task_brief.py --pack ind_as_115 [--out FILE]

Placeholders show as the parameter and its allowed range, because variants and answer keys come
from T51. The brief includes what students never see: the rubric, the planted discrepancies and
the model answer.
"""
from __future__ import annotations

import argparse
import string
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tutor.content import load_pack
from tutor.contracts.skills import ParamSpec, TaskTemplate
from tutor.review import status_table
from tutor.jobs import load_job_profiles
from tutor.skills.drills import choice_check, display, formula_answers, mistake_value, numeric_check
from tutor.skills.loader import learning_order, load_skills, load_tasks

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def rupees(raw: str) -> str:
    """Indian digit grouping: 12345678 -> 1,23,45,678."""
    sign, digits = ("-", raw[1:]) if raw.startswith("-") else ("", raw)
    whole, _, frac = digits.partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    grouped = ",".join(([head] if head else []) + groups + [tail]) if head or groups else tail
    return f"{sign}{grouped}" + (f".{frac}" if frac else "")


def describe(name: str, spec: ParamSpec) -> str:
    label = name.replace("_", " ")
    if spec.choices:
        return f"[{label}: one of {', '.join(spec.choices)}]"
    if spec.type == "money":
        return f"[{label}: ₹{rupees(spec.min or '?')} to ₹{rupees(spec.max or '?')}]"
    if spec.type == "percent":
        return f"[{label}: {spec.min}% to {spec.max}%]"
    return f"[{label}: {spec.min} to {spec.max}]"


def fill(text: str, task: TaskTemplate, extra: dict[str, str] | None = None) -> str:
    values = {**task.company, **{n: describe(n, s) for n, s in task.params.items()}, **(extra or {})}
    out = []
    for literal, field, _, _ in string.Formatter().parse(text):
        value = values.get(field, "{" + field + "}") if field is not None else ""
        # "₹{price}" with a range description would print the symbol twice.
        out.append(literal[:-1] if value.startswith("[") and "₹" in value and literal.endswith("₹") else literal)
        out.append(value)
    return "".join(out)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def task_block(task: TaskTemplate, status: str) -> list[str]:
    lines = [f"### {task.title}", "", f"`{task.task_id}` · {task.kind} · calculator `{task.calculator}` · "
             f"pass mark {task.pass_threshold} · review status **{status}**", "", "#### Brief (what the student sees)", ""]
    lines += [f"> {para}" if para else ">" for para in fill(task.narrative_template, task).split("\n")]
    for doc in task.documents:
        lines += ["", f"**{fill(doc.title, task)}**", "", "| Row | " + " | ".join(doc.columns) + " |",
                  "|---|" + "---|" * len(doc.columns)]
        for row in doc.rows:
            values = []
            for col in doc.columns:
                value = fill(row.get(col, ""), task)
                values.append(cell(rupees(value) if col == "amount_inr" and value.lstrip("-").isdigit() else value))
            lines.append(f"| {row.get('row_id', '')} | " + " | ".join(values) + " |")
    if task.constraints:
        lines += ["", "Parameter rules (every variant satisfies them): " + "; ".join(f"`{c}`" for c in task.constraints)]
    lines += ["", "#### Rubric (hidden from the student)", "", "| Item | Weight | Required | Check | What earns it | Concept | Paragraphs |",
              "|---|---|---|---|---|---|---|"]
    for item in task.rubric:
        check = item.check.type + (f" `{item.check.field}` ±{item.check.tolerance}" if item.check.type == "numeric" else "")
        paras = ", ".join(p.split(".para.")[-1] for p in item.passage_ids)
        lines.append(f"| {item.id} | {item.weight:g} | {'yes' if item.required else ''} | {cell(check)} | {cell(item.text)} | "
                     f"`{item.node_id.split('.', 1)[-1]}` | {paras} |")
    if task.planted_discrepancies:
        lines += ["", "#### Planted issues (hidden)", "", "| Id | Row | Issue | Concept | Paragraphs |", "|---|---|---|---|---|"]
        for d in task.planted_discrepancies:
            paras = ", ".join(p.split(".para.")[-1] for p in d.passage_ids)
            lines.append(f"| {d.id} | {d.row_id} | {d.issue_type.replace('_', ' ')} | `{d.node_id.split('.', 1)[-1]}` | {paras} |")
    answers = {f: f"[{f.replace('_', ' ')}: computed by T51]" for f in task.answer_fields}
    lines += ["", "#### Model answer (hidden)", "", fill(task.model_answer_template, task, answers), ""]
    return lines


def example_values(task: TaskTemplate) -> dict[str, str]:
    """The worked example, formatted the way a student would read it."""
    values = {}
    for name, value in task.example_params.items():
        kind = task.params[name].type
        values[name] = rupees(value) if kind == "money" else f"{value}%" if kind == "percent" else value
    return values


def tolerance_words(tolerance: str) -> str:
    if "|" in tolerance:
        relative, absolute = tolerance.split("|")
        return f"{relative} or ₹{rupees(absolute)}, whichever is larger"
    return f"{tolerance} percentage points" if tolerance == "0.1" else tolerance


def amount(value, tolerance: str) -> str:
    text = display(value, tolerance)
    return text if tolerance == "0.1" else rupees(text)


def drill_block(task: TaskTemplate, status: str) -> list[str]:
    example = example_values(task)
    lines = [f"#### {task.title}", "", f"`{task.task_id}` · review status **{status}**", ""]
    lines += [f"> {para}" if para else ">" for para in fill(task.narrative_template, task, example).split("\n")]
    check = choice_check(task)
    if check is not None:
        lines += ["", "Options: " + " · ".join(f"**{o}**" if o == check.correct else o for o in task.options),
                  "", f"Answer: **{check.correct}**"]
        wrong = [(m.choice, m.feedback) for m in task.mistakes]
        answers: dict[str, str] = {}
    else:
        (field,) = task.answer_fields
        tolerance = numeric_check(task, field).tolerance
        key = formula_answers(task, task.example_params)[field]
        answers = {field: amount(key, tolerance)}
        unit = "%" if tolerance == "0.1" else ""
        lines += ["", f"Answer on this example: **{answers[field]}{unit}** (formula `{task.answer_exprs[field]}`, "
                      f"accepted within {tolerance_words(tolerance)})"]
        wrong = [(f"{amount(mistake_value(m, task.example_params), tolerance)}{unit}", m.feedback) for m in task.mistakes]
    lines += ["", f"Teaching after any answer: {fill(task.explanation, task, {**example, **answers})}", "",
              "| Wrong answer | Feedback |", "|---|---|"]
    lines += [f"| {cell(w)} | {cell(fill(fb, task, {**example, **answers}))} |" for w, fb in wrong]
    item = task.rubric[0]
    paras = ", ".join(p.split(".para.")[-1] for p in item.passage_ids)
    lines += ["", f"Concept `{item.node_id.split('.', 1)[-1]}` · paragraphs {paras}", ""]
    return lines


def skill_map(skills, jobs) -> list[str]:
    lines = ["## Skill map", "", "| Skill | Level | Needs first | Tasks |", "|---|---|---|---|"]
    for skill in learning_order(skills):
        needs = ", ".join(skills[r].title for r in skill.requires if r in skills) or "-"
        lines.append(f"| {skill.title} | {skill.level} | {needs} | {len(skill.task_ids)} |")
    lines += ["", "| Job | Skills it needs |", "|---|---|"]
    for job in jobs.values():
        lines.append(f"| {job.title} | " + ", ".join(skills[s].title for s in job.skills if s in skills) + " |")
    return lines + [""]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    pack = load_pack(args.pack, packs_dir=args.packs_dir)
    skills, tasks = load_skills(pack), load_tasks(pack)
    table = status_table(pack)
    lines = [f"# Skill task briefs: {pack.pack_id} {pack.manifest.version}", ""]
    lines += skill_map(skills, load_job_profiles(pack))
    for skill in learning_order(skills):
        heading = "## Small skill" if skill.level == "micro" else "## Final case study"
        lines += [f"{heading}: {skill.title}", "", f"`{skill.skill_id}` · {skill.description} Passed when all "
                  f"{len(skill.task_ids)} tasks pass.", ""]
        for task_id in skill.task_ids:
            task, status = tasks[task_id], table[f"task:{task_id}"][1]
            lines += drill_block(task, status) if task.kind == "drill" else task_block(task, status)
    out = args.out or SERVICE_ROOT / "data" / "reviews" / f"{pack.pack_id}-{pack.manifest.version}-task-briefs.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
