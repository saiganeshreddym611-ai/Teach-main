"""Safe arithmetic for task constraints: `evaluate("fee * 12 > cost", params)`.

Parsed with `ast` and walked by hand. Allowed: decimal numbers, parameter names, `+ - * /`,
unary minus and plus, comparisons (chains too), `and`, `or`, `not`, parentheses. Everything else
(calls, attributes, subscripts, lambdas, strings, `**`, names outside the parameters) raises
`ExprError`. Never `eval` or `exec`. Numbers are `Decimal`, so results are exact.
"""
from __future__ import annotations

import ast
import operator
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

MAX_LENGTH = 500

_ARITH = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class ExprError(ValueError):
    """The expression is not allowed or cannot be evaluated."""


def parse(expr: str) -> ast.Expression:
    """Parse and check the whole tree before anything runs."""
    if not isinstance(expr, str) or not expr.strip():
        raise ExprError("empty expression")
    if len(expr) > MAX_LENGTH:
        raise ExprError(f"expression longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"not allowed: {type(node).__name__}")
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float))):
            raise ExprError(f"not allowed: constant {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) not in _ARITH:
            raise ExprError(f"not allowed: operator {type(node.op).__name__}")
        if isinstance(node, ast.Compare) and any(type(op) not in _COMPARE for op in node.ops):
            raise ExprError("not allowed: comparison operator")
    return tree


def names(expr: str) -> set[str]:
    """The parameter names an expression uses."""
    return {node.id for node in ast.walk(parse(expr)) if isinstance(node, ast.Name)}


def evaluate(expr: str, params: dict[str, str]) -> Decimal | bool:
    tree = parse(expr)
    source = expr.strip()
    values: dict[str, Decimal] = {}
    for name in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}:
        if name not in params:
            raise ExprError(f"unknown name: {name}")
        values[name] = _number(params[name], name)
    with localcontext() as ctx:
        ctx.prec = 34
        ctx.traps[DivisionByZero] = True
        ctx.traps[InvalidOperation] = True
        try:
            return _eval(tree.body, values, source)
        except (DivisionByZero, InvalidOperation) as exc:
            raise ExprError(f"cannot evaluate: {type(exc).__name__}") from exc


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Name, ast.Load, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


def _number(raw: str, name: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise ExprError(f"{name} is not a number: {raw!r}") from exc
    if not value.is_finite():
        raise ExprError(f"{name} is not a finite number")
    return value


def _eval(node: ast.AST, values: dict[str, Decimal], source: str) -> Decimal | bool:
    if isinstance(node, ast.Constant):
        # The literal as written, so 0.1 stays exactly 0.1 (no float round trip).
        return Decimal(ast.get_source_segment(source, node) or repr(node.value))
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, values, source)
        if isinstance(node.op, ast.Not):
            return not _bool(operand)
        value = _dec(operand)
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.BinOp):
        return _ARITH[type(node.op)](_dec(_eval(node.left, values, source)), _dec(_eval(node.right, values, source)))
    if isinstance(node, ast.Compare):
        left = _dec(_eval(node.left, values, source))
        for op, right_node in zip(node.ops, node.comparators):
            right = _dec(_eval(right_node, values, source))
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        results = (_bool(_eval(v, values, source)) for v in node.values)
        return all(results) if isinstance(node.op, ast.And) else any(results)
    raise ExprError(f"not allowed: {type(node).__name__}")  # parse() already refuses these


def _dec(value: Decimal | bool) -> Decimal:
    if isinstance(value, bool):
        raise ExprError("a true/false value used as a number")
    return value


def _bool(value: Decimal | bool) -> bool:
    if not isinstance(value, bool):
        raise ExprError("a number used as true/false")
    return value
