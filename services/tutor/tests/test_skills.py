"""T50: skill and task templates, the safe expression evaluator, and the validator checks."""
from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import validate_pack
from tutor.content import clear_pack_cache, load_pack
from tutor.review import status_table
from tutor.skills import CALCULATOR_NAMES, ExprError, evaluate, load_skills, load_tasks

PACKS = Path(__file__).resolve().parents[3] / "content" / "packs"
TASK_IDS = {"rr_fixed_price_cost_to_cost", "rr_contract_modification", "rr_variable_consideration", "rr_discrepancy_hunt"}


@pytest.fixture
def pack115():
    clear_pack_cache()
    yield load_pack("ind_as_115")
    clear_pack_cache()


def test_templates_load(pack115):
    skills = load_skills(pack115)
    tasks = {k: t for k, t in load_tasks(pack115).items() if t.kind != "drill"}  # drills: tests/test_micro_skills.py
    skill = skills["revenue_recognition_services"]
    assert skill.level == "capstone"
    assert set(skill.task_ids) == TASK_IDS == set(tasks)
    for task in tasks.values():
        assert task.skill_id == skill.skill_id
        assert task.calculator in CALCULATOR_NAMES
        assert task.pass_threshold == 0.75
        assert "0.5% or ₹1,000" in task.narrative_template and "1 April to 31 March" in task.narrative_template
        if task.kind == "calculation":  # HUMAN-DECISIONS 7.3: about half numbers, half judgement
            numbers = sum(r.weight for r in task.rubric if r.check.type == "numeric")
            assert numbers == pytest.approx(0.5), task.task_id
    hunt = tasks["rr_discrepancy_hunt"]
    assert len(hunt.planted_discrepancies) == 4
    assert {d.issue_type for d in hunt.planted_discrepancies} == {
        "premature_revenue", "duplicate_billing", "missing_credit_note", "wrong_period"}


@pytest.mark.parametrize(
    ("expr", "params", "expected"),
    [
        ("a + b * 2", {"a": "0.1", "b": "0.2"}, Decimal("0.5")),
        ("(a + b) / 3", {"a": "1", "b": "2"}, Decimal("1")),
        ("-a + 0.1", {"a": "0.3"}, Decimal("-0.2")),
        ("price * 0.85 >= cost", {"price": "1000000", "cost": "850000"}, True),
        ("p0 + p1 + p2 == 100", {"p0": "70", "p1": "20", "p2": "10"}, True),
        ("0 < a < 1 and not b > 2 or a == 5", {"a": "0.5", "b": "1"}, True),
        ("a != a", {"a": "3"}, False),
    ],
    ids=["decimal-exact", "parentheses", "unary-minus", "comparison", "sum-equals", "bool-chain", "not-equal"],
)
def test_expr_allows_arithmetic_and_comparisons(expr, params, expected):
    result = evaluate(expr, params)
    assert result == expected and type(result) is type(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "abs(a)",
        "a.real",
        "a[0]",
        "(lambda: 1)()",
        "a ** 2",
        "a // 2",
        "'text' == a",
        "x + 1",
        "a if a else 1",
        "[a]",
        "a is a",
        "a in a",
        "True",
        "",
    ],
    ids=["import", "call", "attribute", "subscript", "lambda", "power", "floor-div", "string", "unknown-name",
         "conditional", "list", "is", "in", "bool-constant", "empty"],
)
def test_expr_rejects_unsafe(expr):
    with pytest.raises(ExprError):
        evaluate(expr, {"a": "2"})


@pytest.mark.parametrize(
    ("expr", "params"),
    [("a / b", {"a": "1", "b": "0"}), ("a + 1", {"a": "ten"}), ("a and 1 > 0", {"a": "1"}), ("(a > 1) + 1", {"a": "2"})],
    ids=["division-by-zero", "not-a-number", "number-as-bool", "bool-as-number"],
)
def test_expr_errors_are_expr_errors(expr, params):
    with pytest.raises(ExprError):
        evaluate(expr, params)


def test_validator_passes_on_drafts(capsys):
    clear_pack_cache()
    assert validate_pack.main(["--pack", "ind_as_115"]) == 0
    out = capsys.readouterr().out
    assert "passage IDs in tasks were not checked" in out  # no corpus until H1
    assert "6 skills and 24 tasks are consistent" in out


def _edit_task(task: dict, case: str) -> None:
    if case == "bad_node":
        task["rubric"][0]["node_id"] = "ind_as_115.step_9"
    elif case == "weights":
        task["rubric"][0]["weight"] = round(task["rubric"][0]["weight"] - 0.1, 6)
    elif case == "placeholder":
        task["narrative_template"] += " Due on {due_date}."
    elif case == "missing_row":
        task["planted_discrepancies"][0]["row_id"] = "R99"
    elif case == "constraint":
        task["constraints"].append("__import__('os')")
    elif case == "calculator":
        task["calculator"] = "magic_numbers"


@pytest.mark.parametrize(
    ("case", "task_id", "message"),
    [
        ("bad_node", "rr_fixed_price_cost_to_cost", "node 'ind_as_115.step_9' is not in the concept map"),
        ("weights", "rr_fixed_price_cost_to_cost", "rubric weights sum to 0.9, not 1.0"),
        ("placeholder", "rr_contract_modification", "placeholder '{due_date}' has no parameter"),
        ("missing_row", "rr_discrepancy_hunt", "row 'R99' is not in any document"),
        ("constraint", "rr_variable_consideration", "not allowed: Call"),
        ("calculator", "rr_variable_consideration", "calculator 'magic_numbers' is not registered"),
    ],
    ids=["bad-node", "weights-0.9", "missing-placeholder-param", "missing-row", "bad-constraint", "unknown-calculator"],
)
def test_validator_catches_broken(tmp_path, capsys, case, task_id, message):
    packs = tmp_path / "packs"
    shutil.copytree(PACKS / "ind_as_115", packs / "ind_as_115")
    path = packs / "ind_as_115" / "tasks" / f"{task_id}.json"
    task = json.loads(path.read_text(encoding="utf-8"))
    _edit_task(task, case)
    path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    clear_pack_cache()
    try:
        assert validate_pack.main(["--pack", "ind_as_115", "--packs-dir", str(packs)]) == 1
    finally:
        clear_pack_cache()
    out = capsys.readouterr().out
    assert f"FAIL: task {task_id}: " in out and message in out


def test_tasks_start_as_draft(pack115):
    table = status_table(pack115)
    new_items = {"skill:revenue_recognition_services"} | {f"task:{t}" for t in TASK_IDS}
    assert new_items <= set(table)
    assert all(table[item] == ("task", "draft") for item in new_items)
