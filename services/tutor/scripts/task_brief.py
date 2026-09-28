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
from tutor.skills.loader import load_skills, load_tasks

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
    lines = [f"## {task.title}", "", f"`{task.task_id}` · {task.kind} · calculator `{task.calculator}` · "
             f"pass mark {task.pass_threshold} · review status **{status}**", "", "### Brief (what the student sees)", ""]
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
    lines += ["", "### Rubric (hidden from the student)", "", "| Item | Weight | Required | Check | What earns it | Concept | Paragraphs |",
              "|---|---|---|---|---|---|---|"]
    for item in task.rubric:
        check = item.check.type + (f" `{item.check.field}` ±{item.check.tolerance}" if item.check.type == "numeric" else "")
        paras = ", ".join(p.split(".para.")[-1] for p in item.passage_ids)
        lines.append(f"| {item.id} | {item.weight:g} | {'yes' if item.required else ''} | {cell(check)} | {cell(item.text)} | "
                     f"`{item.node_id.split('.', 1)[-1]}` | {paras} |")
    if task.planted_discrepancies:
        lines += ["", "### Planted issues (hidden)", "", "| Id | Row | Issue | Concept | Paragraphs |", "|---|---|---|---|---|"]
        for d in task.planted_discrepancies:
            paras = ", ".join(p.split(".para.")[-1] for p in d.passage_ids)
            lines.append(f"| {d.id} | {d.row_id} | {d.issue_type.replace('_', ' ')} | `{d.node_id.split('.', 1)[-1]}` | {paras} |")
    answers = {f: f"[{f.replace('_', ' ')}: computed by T51]" for f in task.answer_fields}
    lines += ["", "### Model answer (hidden)", "", fill(task.model_answer_template, task, answers), ""]
    return lines


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
    for skill in skills.values():
        lines += [f"**Skill:** {skill.title} (`{skill.skill_id}`, unlocks when all {len(skill.task_ids)} tasks pass). "
                  f"{skill.description}", ""]
        for task_id in skill.task_ids:
            lines += task_block(tasks[task_id], table[f"task:{task_id}"][1])
    out = args.out or SERVICE_ROOT / "data" / "reviews" / f"{pack.pack_id}-{pack.manifest.version}-task-briefs.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
