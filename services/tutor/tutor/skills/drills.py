"""Drill answers and tolerances (T55). Drills are short enough that each answer is a formula of
the params, so they need no hand-written calculator."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ..contracts.skills import ChoiceCheck, Mistake, NumericCheck, TaskTemplate
from .expr import ExprError, evaluate


def within(value: Decimal, key: Decimal, tolerance: str) -> bool:
    """`tolerance` is "1000", "0.5%" or "0.5%|1000" (the larger of the two, HUMAN-DECISIONS 7.3)."""
    relative, _, absolute = tolerance.partition("|") if "%" in tolerance else ("", "", tolerance)
    allowed = Decimal(absolute or "0")
    if relative:
        allowed = max(allowed, abs(key) * Decimal(relative.rstrip("%")) / 100)
    return abs(value - key) <= allowed


def display(value: Decimal, tolerance: str) -> str:
    """Round the way the brief asks: one decimal for a percentage key, whole rupees for amounts."""
    places = Decimal("0.1") if tolerance == "0.1" else Decimal("1")
    return str(value.quantize(places, rounding=ROUND_HALF_UP))


def formula_answers(task: TaskTemplate, params: dict[str, str]) -> dict[str, Decimal]:
    answers = {}
    for name, expr in task.answer_exprs.items():
        value = evaluate(expr, params)
        if isinstance(value, bool):
            raise ExprError(f"answer '{name}' is true/false, not a number")
        answers[name] = value
    return answers


def mistake_value(mistake: Mistake, params: dict[str, str]) -> Decimal:
    value = evaluate(mistake.expr, params)
    if isinstance(value, bool):
        raise ExprError("a mistake expression must give a number")
    return value


def numeric_check(task: TaskTemplate, field: str) -> NumericCheck | None:
    return next((r.check for r in task.rubric if isinstance(r.check, NumericCheck) and r.check.field == field), None)


def choice_check(task: TaskTemplate) -> ChoiceCheck | None:
    return next((r.check for r in task.rubric if isinstance(r.check, ChoiceCheck)), None)
