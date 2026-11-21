"""Tiny, safe math plotting for the Study skill.

Expressions are parsed with `ast` and only a small whitelist of nodes is
allowed. There is no eval of arbitrary Python. Output is a compact text plot
that a small model can paste straight into an answer.
"""

from __future__ import annotations

import ast
import math

BLOCKS = " ▁▂▃▄▅▆▇█"
ALLOWED_NAMES = {"x", "pi", "e", "sin", "cos", "tan", "sqrt", "abs", "log", "exp"}
FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "abs": abs, "log": math.log, "exp": math.exp,
}


class MathError(Exception):
    pass


def compile_expr(expression: str):
    source = str(expression or "").strip()
    if not source or len(source) > 160:
        raise MathError("empty or too-long expression")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise MathError("could not parse expression") from exc

    allowed_nodes = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
        ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
        ast.USub, ast.UAdd,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise MathError(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in ALLOWED_NAMES:
            raise MathError(f"unknown name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
                raise MathError("only simple math functions are allowed")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise MathError("only numbers are allowed")

    def run(x: float):
        return float(eval(compile(tree, "<math>", "eval"), {
            "__builtins__": {}, **FUNCS, "pi": math.pi, "e": math.e,
            "x": x,
        }))

    return run


def plot(expression: str, xmin: float = -3.14, xmax: float = 3.14,
         width: int = 48, height: int = 9) -> str:
    fn = compile_expr(expression)
    width = max(16, min(int(width), 80))
    height = max(4, min(int(height), 16))
    xs = [xmin + (xmax - xmin) * i / (width - 1) for i in range(width)]
    try:
        values = [fn(x) for x in xs]
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise MathError(f"could not evaluate: {exc}") from exc
    finite = [v for v in values if math.isfinite(v)]
    if not finite:
        raise MathError("no finite values in range")
    low, high = min(finite), max(finite)
    span = (high - low) or 1.0

    rows = []
    for row in range(height):
        level = high - span * row / (height - 1)
        chars = []
        for value in values:
            if not math.isfinite(value):
                chars.append(" ")
                continue
            index = round((high - value) / span * (height - 1))
            chars.append("●" if index == row else "·" if abs(index - row) == 1 else " ")
        rows.append("".join(chars).rstrip())

    spark = "".join(
        BLOCKS[min(len(BLOCKS) - 1, max(0, round((v - low) / span * (len(BLOCKS) - 1))))]
        if math.isfinite(v) else " "
        for v in values[::2]
    )
    return (
        f"Plot of y = {expression}\n"
        f"range x=[{xmin}, {xmax}]  y=[{round(low, 3)}, {round(high, 3)}]\n"
        + "\n".join(rows)
        + f"\nsparkline: {spark}"
    )


def evaluate(expression: str, x: float = 0.0) -> str:
    fn = compile_expr(expression)
    try:
        value = fn(float(x))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise MathError(f"could not evaluate: {exc}") from exc
    return f"f({x}) = {round(value, 6)}"
