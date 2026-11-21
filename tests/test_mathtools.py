"""Tests for the safe math plot tool."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mathtools  # noqa: E402
import registry  # noqa: E402


class Math(unittest.TestCase):
    def test_real_plots(self):
        for expression in ("x**2", "sin(x)", "sqrt(abs(x))"):
            with self.subTest(expression=expression):
                text = mathtools.plot(expression, width=24, height=6)
                self.assertIn("Plot of y =", text)
                self.assertIn("sparkline:", text)

    def test_evaluate(self):
        self.assertIn("4.0", mathtools.evaluate("x**2", 2))
        self.assertIn("1.0", mathtools.evaluate("sin(x)", 1.57079632679))

    def test_no_code_execution(self):
        for expression in (
            "__import__('os').system('ls')", "open('/etc/passwd').read()",
            "lambda x: x", "[x for x in range(3)]", "x.__class__",
        ):
            with self.subTest(expression=expression), self.assertRaises(mathtools.MathError):
                mathtools.compile_expr(expression)

    def test_registered(self):
        result = registry.run("plot_function", {"expression": "x**2", "width": 20})
        self.assertTrue(result["ok"])
        self.assertIn("Plot of", result["data"])
