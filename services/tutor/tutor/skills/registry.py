"""Calculator names the task templates may use. T51 registers the functions behind them."""
from __future__ import annotations

CALCULATOR_NAMES: tuple[str, ...] = (
    "cost_to_cost",            # progress, revenue and contract asset or liability (paras 39-45, B18-B19, 105-107)
    "contract_modification",   # cumulative catch-up for a modification that is part of the contract (para 21(b))
    "variable_consideration",  # expected value, most likely amount and the constraint (paras 50-59)
    "cutoff_check",            # the hunt: planted issues present, no unplanned ones, net revenue adjustment
    "formula",                 # drills: each answer field is an expression of the params (`answer_exprs`)
    "choice",                  # drills: the answer is the correct option
)
