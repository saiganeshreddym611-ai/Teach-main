"""T55: micro skills, drills with instant feedback, and jobs built from sets of skills."""
from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import validate_pack
from tutor.content import clear_pack_cache, load_pack
from tutor.contracts.skills import ChoiceCheck
from tutor.jobs import load_job_profiles
from tutor.skills import load_skills, load_tasks
from tutor.skills.drills import choice_check, display, formula_answers, mistake_value, numeric_check, within

PACKS = Path(__file__).resolve().parents[3] / "content" / "packs"
MICRO = {"ms_over_time_or_point", "ms_cost_to_cost_progress", "ms_inefficiency_costs",
         "ms_contract_asset_liability", "ms_revenue_for_period"}


@pytest.fixture
def pack115():
    clear_pack_cache()
    yield load_pack("ind_as_115")
    clear_pack_cache()


def test_micro_skills_and_capstone(pack115):
    skills = load_skills(pack115)
    tasks = load_tasks(pack115)
    assert {s for s, skill in skills.items() if skill.level == "micro"} == MICRO
    for skill_id in MICRO:
        drills = [tasks[t] for t in skills[skill_id].task_ids]
        assert len(drills) == 4 and all(d.kind == "drill" and d.pass_threshold == 1.0 for d in drills), skill_id
    assert set(skills["revenue_recognition_services"].requires) == MICRO


# Worked by hand from each drill's example_params; the formulas must agree.
@pytest.mark.parametrize(
    ("task_id", "expected"),
    [
        ("dr_ctc_progress", "37.5"),
        ("dr_ctc_revenue", "3750000"),
        ("dr_ctc_cost_to_complete", "40.0"),
        ("dr_ctc_revised_estimate", "40.0"),
        ("dr_ineff_progress_ex_rework", "40.0"),
        ("dr_ineff_uninstalled_servers", "21000000"),
        ("dr_cal_balance", "1500000"),
        ("dr_rfp_second_year", "4800000"),
        ("dr_rfp_estimate_revised", "7000000"),
        ("dr_rfp_given_last_year", "4500000"),
    ],
)
def test_numeric_drill_answers_on_examples(pack115, task_id, expected):
    task = load_tasks(pack115)[task_id]
    (field,) = task.answer_fields
    value = formula_answers(task, task.example_params)[field]
    assert display(value, numeric_check(task, field).tolerance) == expected


def test_every_mistake_is_wrong_and_every_wrong_option_has_feedback(pack115):
    for task in (t for t in load_tasks(pack115).values() if t.kind == "drill"):
        assert task.explanation and task.mistakes, task.task_id
        check = choice_check(task)
        if check is not None:
            wrong = set(task.options) - {check.correct}
            assert {m.choice for m in task.mistakes} == wrong, task.task_id
            continue
        (field,) = task.answer_fields
        key = formula_answers(task, task.example_params)[field]
        for mistake in task.mistakes:
            assert not within(mistake_value(mistake, task.example_params), key, numeric_check(task, field).tolerance)


def test_jobs_need_different_skill_sets(pack115):
    jobs = load_job_profiles(pack115)
    accountant, billing = jobs["revenue_accountant_seed"], jobs["billing_executive_seed"]
    assert MICRO <= set(accountant.skills) and "revenue_recognition_services" in accountant.skills
    assert set(billing.skills) == {"ms_contract_asset_liability", "ms_over_time_or_point"}


@pytest.mark.parametrize(
    ("value", "key", "tolerance", "ok"),
    [("100500", "100000", "0.5%|1000", True), ("101001", "100000", "0.5%|1000", False),
     ("10050000", "10000000", "0.5%|1000", True), ("37.6", "37.5", "0.1", True), ("37.7", "37.5", "0.1", False)],
    ids=["abs-floor", "past-abs", "relative", "percent-in", "percent-out"],
)
def test_within_tolerance(value, key, tolerance, ok):
    assert within(Decimal(value), Decimal(key), tolerance) is ok


def _edit(packs: Path, case: str) -> None:
    pack = packs / "ind_as_115"

    def load(kind: str, name: str) -> tuple[Path, dict]:
        path = pack / kind / f"{name}.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    if case == "mistake-is-right":
        path, data = load("tasks", "dr_ctc_progress")
        data["mistakes"][0]["expr"] = "costs_to_date / total_cost * 100"
    elif case == "correct-not-an-option":
        path, data = load("tasks", "dr_cal_paid_in_advance")
        data["rubric"][0]["check"]["correct"] = "Deferred revenue"
    elif case == "example-breaks-constraint":
        path, data = load("tasks", "dr_ctc_revenue")
        data["example_params"]["costs_to_date"] = "7900000"
    elif case == "requires-loop":
        path, data = load("skills", "ms_over_time_or_point")
        data["requires"] = ["ms_revenue_for_period"]
    elif case == "unknown-job-skill":
        path, data = load("job_profiles", "billing_executive")
        data["skills"].append("ms_does_not_exist")
    elif case == "capstone-in-micro":
        path, data = load("skills", "ms_contract_asset_liability")
        data["task_ids"].append("rr_discrepancy_hunt")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("mistake-is-right", "dr_ctc_progress: mistake 1: on the example it gives the right answer"),
        ("correct-not-an-option", "correct answer 'Deferred revenue' is not one of the options"),
        ("example-breaks-constraint", "example breaks constraint 'costs_to_date <= total_cost * 0.9'"),
        ("requires-loop", "skill ms_over_time_or_point: its requires chain loops back to itself"),
        ("unknown-job-skill", "job billing_executive_seed: skill 'ms_does_not_exist' does not exist"),
        ("capstone-in-micro", "micro skills hold drills and capstones hold the rest"),
    ],
    ids=lambda v: v if v.count(" ") == 0 else None,
)
def test_validator_catches_drill_problems(tmp_path, capsys, case, message):
    packs = tmp_path / "packs"
    shutil.copytree(PACKS / "ind_as_115", packs / "ind_as_115")
    _edit(packs, case)
    clear_pack_cache()
    try:
        assert validate_pack.main(["--pack", "ind_as_115", "--packs-dir", str(packs)]) == 1
    finally:
        clear_pack_cache()
    assert message in capsys.readouterr().out


def test_choice_check_round_trips():
    check = ChoiceCheck.model_validate({"type": "choice", "field": "choice", "correct": "Contract asset"})
    assert check.correct == "Contract asset"
