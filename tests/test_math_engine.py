"""Tests for the dependency-free math engine: evaluation, symbols, and solving."""

import pytest

from math_engine import MathError, evaluate, solve, solve_math


# ---------------------------------------------------------------------------
# Expression evaluation
# ---------------------------------------------------------------------------


def test_evaluate_basic_arithmetic():
    assert evaluate("2 + 3 * 4") == 14.0
    assert evaluate("(2 + 3) * 4") == 20.0
    assert evaluate("10 / 4") == 2.5
    assert evaluate("2^10") == 1024.0


def test_evaluate_division_by_zero_is_math_error():
    """Division by zero must surface as MathError, never a raw exception."""
    with pytest.raises(MathError):
        evaluate("1/0")
    with pytest.raises(MathError):
        evaluate("1/(2-2)")  # zero denominator produced by evaluation


def test_solve_division_by_zero_constant_does_not_crash():
    """A zero constant denominator must not KeyError in the polynomial path."""
    result = solve("1/0")
    assert isinstance(result, dict)
    assert result.get("solutions") == []
    out = solve_math("1/0")
    assert isinstance(out, str)
    assert "KeyError" not in out and "ZeroDivisionError" not in out


def test_evaluate_unicode_symbols():
    assert evaluate("√16") == 4.0
    assert evaluate("√16 × 3 ÷ 2") == 6.0
    with pytest.raises(MathError):
        evaluate("x²")  # x is an unknown symbol without an equation


def test_evaluate_superscripts():
    assert evaluate("3² + 4²") == 25.0
    assert evaluate("2³") == 8.0
    assert evaluate("5²") == 25.0


def test_evaluate_implicit_multiplication():
    assert evaluate("2pi") == pytest.approx(6.283185307)
    assert evaluate("3(4+5)") == 27.0
    assert evaluate("2sqrt(4)") == 4.0
    assert evaluate("50% of 200") == 100.0


def test_evaluate_functions_and_constants():
    assert evaluate("sqrt(144) + 2^5") == 44.0
    assert evaluate("sin(pi/2)") == pytest.approx(1.0)
    assert evaluate("log2(8) * 10") == 30.0
    assert evaluate("log10(100)") == 2.0
    assert evaluate("atan2(1, 1)") == pytest.approx(0.7853981634)
    assert evaluate("factorial(5)") == 120.0
    assert evaluate("5!") == 120.0
    assert evaluate("ln(e)") == pytest.approx(1.0)
    assert evaluate("gcd(12, 8)") == 4.0


def test_evaluate_rejects_unsafe_code():
    with pytest.raises(MathError):
        evaluate("__import__('os').system('dir')")
    with pytest.raises(MathError):
        evaluate("open('memory.json')")


def test_solve_math_formats_expression():
    result = solve_math("sqrt(144) + 2^5")
    assert "Result: 44" in result


# ---------------------------------------------------------------------------
# Equation solving
# ---------------------------------------------------------------------------


def test_solve_linear():
    solved = solve("2x + 3 = 11")
    assert solved["solutions"] == ["4"]
    assert solved["method"] == "exact"


def test_solve_linear_with_implicit_multiplication():
    solved = solve("3x + 2 = 14")
    assert solved["solutions"] == ["4"]


def test_solve_quadratic_two_roots():
    solved = solve("x^2 - 5x + 6 = 0")
    assert sorted(float(s) for s in solved["solutions"]) == [2.0, 3.0]


def test_solve_quadratic_superscript():
    solved = solve("x² + 2x + 1 = 0")
    assert solved["solutions"] == ["-1"]


def test_solve_quadratic_no_real_roots():
    solved = solve("x^2 + 1 = 0")
    assert solved["solutions"] == []


def test_solve_quadratic_factored_form():
    solved = solve("3x(2x + 1) = 0")
    assert sorted(float(s) for s in solved["solutions"]) == [-0.5, 0.0]


def test_solve_x_squared_equals_constant():
    solved = solve("x^2 = 4")
    assert sorted(float(s) for s in solved["solutions"]) == [-2.0, 2.0]


def test_solve_division_form():
    solved = solve("x/4 = 3")
    assert solved["solutions"] == ["12"]


def test_solve_non_polynomial_numeric():
    solved = solve("sqrt(x + 3) = 5")
    assert any(abs(float(s) - 22.0) < 1e-3 for s in solved["solutions"])
    assert solved["method"] == "numeric"


def test_solve_no_roots_for_constant_mismatch():
    solved = solve("1/x = 0")
    assert solved["solutions"] == []


def test_solve_cubic():
    solved = solve("x^3 - 8 = 0")
    assert any(abs(float(s) - 2.0) < 1e-3 for s in solved["solutions"])


def test_solve_math_output_contains_solution():
    result = solve_math("2x + 3 = 11")
    assert "Solutions: x = 4" in result


def test_empty_expression_raises():
    with pytest.raises(MathError):
        evaluate("")
    with pytest.raises(MathError):
        solve("")
