"""Advanced math engine for Nyx Ichos.

A dependency-free evaluator and equation solver that understands math the way
humans write it: unicode symbols (√, ×, ÷, −, superscripts), implicit
multiplication (2π, 3(4+5), 2x), percent signs, named constants (pi, e, tau,
phi), and a broad set of functions (sqrt, trig, logs, factorial, gcd, ...).

Safety: expressions are parsed with Python's ``ast`` module and evaluated by a
whitelist visitor. No ``eval``/``exec`` is used, so arbitrary code cannot run.

Solving: equations are split on ``=``, both sides are converted to a symbolic
polynomial in ``x`` when possible (linear/quadratic solved exactly with
step-by-step notes), and non-polynomial or higher-degree equations are solved
numerically with bisection + Newton refinement.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any, Dict, List, Optional, Tuple


class MathError(ValueError):
    """Raised when an expression cannot be parsed or evaluated."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSTANTS: Dict[str, float] = {
    "pi": math.pi,
    "π": math.pi,
    "tau": math.tau,
    "τ": math.tau,
    "e": math.e,
    "phi": (1 + math.sqrt(5)) / 2,
    "φ": (1 + math.sqrt(5)) / 2,
    "inf": math.inf,
    "nan": math.nan,
}

# Functions the evaluator will allow. Map lowercase name -> callable.
_FUNCS: Dict[str, Any] = {
    "sqrt": math.sqrt,
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "root": lambda x, n=2: math.copysign(abs(x) ** (1.0 / n), x),
    "pow": math.pow,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "log": lambda x, base=10: math.log(x, base),
    "ln": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "lcm": math.lcm,
    "min": min,
    "max": max,
    "hypot": math.hypot,
    "degrees": math.degrees,
    "radians": math.radians,
    "sign": lambda x: (x > 0) - (x < 0),
    "clamp": lambda x, lo, hi: max(lo, min(hi, x)),
    "logistic": lambda x: 1 / (1 + math.exp(-x)),
}

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


# ---------------------------------------------------------------------------
# Normalization: turn human notation into Python-parseable math
# ---------------------------------------------------------------------------


def _normalize(expression: str) -> str:
    """Translate unicode math notation into ASCII Python math syntax."""
    expr = (expression or "").strip()
    if not expr:
        raise MathError("Empty expression.")

    # Unicode operators
    expr = expr.replace("−", "-").replace("–", "-").replace("—", "-")
    expr = expr.replace("×", "*").replace("⋅", "*").replace("·", "*")
    expr = expr.replace("÷", "/").replace("⁄", "/")
    expr = expr.replace("π", "pi").replace("τ", "tau").replace("φ", "phi")

    # Superscripts -> exponentiation: x² -> x**2, handles multi-digit runs
    expr = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "**" + m.group(1).translate(_SUPERSCRIPT), expr)
    # Subscripts -> plain digits (log₂ -> log2)
    expr = re.sub(r"([₀₁₂₃₄₅₆₇₈₉]+)", lambda m: m.group(1).translate(_SUBSCRIPT), expr)

    # Caret exponentiation
    expr = expr.replace("^", "**")

    # Percent: '50%' -> '(50/100)'; '50% of 200' -> '(50/100)*200'
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s+of\s+", r"(\1/100)*", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)

    # Postfix factorial: 5! -> factorial(5) (but not '!=')
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*!(?!=)", r"factorial(\1)", expr)

    # Square root: √(expr) -> sqrt(expr); √number -> sqrt(number); √name -> sqrt(name)
    expr = re.sub(r"√\s*\(", "sqrt(", expr)
    expr = re.sub(r"√\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", expr)
    expr = re.sub(r"√\s*([a-zA-Z_]+)", r"sqrt(\1)", expr)

    # Protect function names (sqrt, sin, log2, atan2, ...) from the implicit
    # multiplication rules below by swapping them for placeholders first.
    func_names = sorted(set(_FUNCS) | {"sqrt"}, key=len, reverse=True)
    protected: List[str] = []

    def _protect(match):
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    func_pattern = r"(?<![a-zA-Z0-9])(" + "|".join(re.escape(name) for name in func_names) + r")(?![a-zA-Z0-9])"
    expr = re.sub(func_pattern, _protect, expr)

    # Implicit multiplication: 2x, 3(4+5), (a)(b), x2, 2pi
    expr = re.sub(r"(?<![a-zA-Z])(\d)([a-zA-Z(])", r"\1*\2", expr)
    expr = re.sub(r"([a-zA-Z)])(\d)(?!\()", r"\1*\2", expr)
    expr = re.sub(r"(\))(\()", r"\1*\2", expr)

    def _implicit_call(match):
        run = match.group(1)
        if run in _FUNCS or run == "sqrt":
            return match.group(0)
        return run + "*("

    expr = re.sub(r"([a-zA-Z]+)\(", _implicit_call, expr)  # xy( -> xy*( when not a function

    # Restore protected function names, inserting '*' where a number/letter
    # directly preceded them (2sqrt(4) -> 2*sqrt(4), xpi -> x*pi).
    def _restore(match):
        index = int(match.group(1))
        name = protected[index]
        previous = expr[match.start() - 1] if match.start() > 0 else ""
        prefix = "*" if (previous.isalnum() or previous == ")") else ""
        return prefix + name

    expr = re.sub(r"\x00(\d+)\x00", _restore, expr)

    # Reject obviously-dangerous constructs (attribute access, calls beyond whitelist)
    for forbidden in ("__", "lambda", "import", "exec", "eval", "open", "getattr"):
        if forbidden in expr.lower():
            raise MathError("Unsupported construct in expression.")

    return expr


# ---------------------------------------------------------------------------
# Safe AST evaluator
# ---------------------------------------------------------------------------

_ALLOWED_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


class _Evaluator(ast.NodeVisitor):
    """Evaluate a parsed math AST using an explicit whitelist."""

    def __init__(self, variables: Optional[Dict[str, float]] = None):
        self.variables = dict(variables or {})

    def visit_Expression(self, node: ast.Expression) -> float:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> float:  # noqa: N802
        if isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise MathError(f"Unsupported constant: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> float:  # noqa: N802
        name = node.id
        if name in self.variables:
            return self.variables[name]
        if name in CONSTANTS:
            return CONSTANTS[name]
        raise MathError(f"Unknown symbol: {name}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:  # noqa: N802
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise MathError("Unsupported unary operator.")

    def visit_BinOp(self, node: ast.BinOp) -> float:  # noqa: N802
        op = type(node.op)
        if op not in _ALLOWED_BIN_OPS:
            raise MathError(f"Unsupported operator: {op.__name__}")
        try:
            return _ALLOWED_BIN_OPS[op](self.visit(node.left), self.visit(node.right))
        except ArithmeticError as error:  # division by zero or overflow
            raise MathError(f"Arithmetic error: {error}") from None

    def visit_Call(self, node: ast.Call) -> float:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise MathError("Unsupported function call.")
        name = node.func.id.lower()
        if name not in _FUNCS:
            raise MathError(f"Unknown function: {name}")
        args = [self.visit(arg) for arg in node.args]
        # Integer-only functions (factorial, gcd, lcm) need ints, not floats.
        if name in ("factorial", "gcd", "lcm"):
            args = [int(arg) if float(arg).is_integer() else arg for arg in args]
        if node.keywords:
            kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords if kw.arg}
        else:
            kwargs = {}
        try:
            return float(_FUNCS[name](*args, **kwargs))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError) as error:
            raise MathError(f"Error evaluating {name}: {error}")

    def visit(self, node: ast.AST):  # noqa: D102
        method = "visit_" + type(node).__name__
        visitor = getattr(self, method, None)
        if visitor is None:
            raise MathError(f"Unsupported syntax: {type(node).__name__}")
        return visitor(node)

    @classmethod
    def evaluate(cls, expression: str, variables: Optional[Dict[str, float]] = None) -> float:
        normalized = _normalize(expression)
        try:
            tree = ast.parse(normalized, mode="eval")
        except SyntaxError as error:
            raise MathError(f"Could not parse expression: {error}")
        return cls(variables).visit(tree)


def evaluate(expression: str, variables: Optional[Dict[str, float]] = None) -> float:
    """Evaluate a math expression and return the numeric result."""
    return _Evaluator.evaluate(expression, variables)


def _format_number(value: float) -> str:
    """Format a float compactly, avoiding trailing float noise."""
    if math.isnan(value):
        return "undefined"
    if math.isinf(value):
        return "infinity" if value > 0 else "-infinity"
    if abs(value) < 1e-12:
        return "0"
    rounded = round(value, 10)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


# ---------------------------------------------------------------------------
# Symbolic polynomial collection (for exact linear/quadratic solving)
# ---------------------------------------------------------------------------


class _Polynomial:
    """A sparse polynomial in x: {degree: coefficient}."""

    def __init__(self, terms: Optional[Dict[int, float]] = None):
        self.terms: Dict[int, float] = {}
        if terms:
            for degree, coeff in terms.items():
                if coeff:
                    self.terms[degree] = self.terms.get(degree, 0.0) + coeff
                    if abs(self.terms[degree]) < 1e-12:
                        del self.terms[degree]

    def degree(self) -> int:
        return max(self.terms) if self.terms else 0

    def __add__(self, other: "_Polynomial") -> "_Polynomial":
        merged = dict(self.terms)
        for degree, coeff in other.terms.items():
            merged[degree] = merged.get(degree, 0.0) + coeff
        return _Polynomial(merged)

    def __sub__(self, other: "_Polynomial") -> "_Polynomial":
        merged = dict(self.terms)
        for degree, coeff in other.terms.items():
            merged[degree] = merged.get(degree, 0.0) - coeff
        return _Polynomial(merged)

    def __mul__(self, other: "_Polynomial") -> "_Polynomial":
        product: Dict[int, float] = {}
        for d1, c1 in self.terms.items():
            for d2, c2 in other.terms.items():
                product[d1 + d2] = product.get(d1 + d2, 0.0) + c1 * c2
        return _Polynomial(product)

    def scale(self, factor: float) -> "_Polynomial":
        return _Polynomial({d: c * factor for d, c in self.terms.items()})

    def evaluate(self, x: float) -> float:
        value = 0.0
        for degree, coeff in self.terms.items():
            value += coeff * (x ** degree)
        return value


def _collect_polynomial(node: ast.AST) -> Optional[_Polynomial]:
    """Convert an AST subtree to a polynomial in x, or None if not polynomial."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return _Polynomial({0: float(node.value)})
    if isinstance(node, ast.Name):
        if node.id == "x":
            return _Polynomial({1: 1.0})
        if node.id in CONSTANTS:
            return _Polynomial({0: CONSTANTS[node.id]})
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        poly = _collect_polynomial(node.operand)
        return poly.scale(-1) if poly is not None else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _collect_polynomial(node.operand)
    if isinstance(node, ast.BinOp):
        left = _collect_polynomial(node.left)
        right = _collect_polynomial(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div) and right.degree() == 0 and right.terms.get(0, 0.0) != 0:
            return left.scale(1.0 / right.terms[0])
        if isinstance(node.op, ast.Pow) and left.degree() == 1 and left.terms.get(0, 0) == 0:
            # (a*x)^n
            if isinstance(right, _Polynomial) and right.degree() == 0:
                exponent = right.terms[0]
                if float(exponent).is_integer() and int(exponent) >= 0:
                    base = _Polynomial({1: left.terms[1]})
                    result = _Polynomial({0: 1.0})
                    for _ in range(int(exponent)):
                        result = result * base
                    return result
        return None
    return None


def _solve_polynomial(poly: _Polynomial) -> Tuple[List[float], List[str]]:
    """Solve a polynomial exactly; returns (roots, steps)."""
    degree = poly.degree()
    if degree == 0:
        if abs(poly.terms.get(0, 0)) < 1e-9:
            return [], ["All real numbers satisfy this equation (0 = 0)."]
        return [], ["No solution: a nonzero constant cannot equal zero."]

    steps: List[str] = []
    if degree == 1:
        a = poly.terms[1]
        b = poly.terms.get(0, 0)
        root = -b / a
        steps.append(f"Linear equation: {a}x + {b} = 0")
        steps.append(f"x = -b / a = {_format_number(root)}")
        return [root], steps

    if degree == 2:
        a = poly.terms.get(2, 0)
        b = poly.terms.get(1, 0)
        c = poly.terms.get(0, 0)
        steps.append(f"Quadratic: {a}x^2 + {b}x + {c} = 0")
        discriminant = b * b - 4 * a * c
        steps.append(f"Discriminant D = b^2 - 4ac = {_format_number(discriminant)}")
        if discriminant < 0:
            steps.append("D < 0, so there are no real solutions.")
            return [], steps
        sqrt_d = math.sqrt(discriminant)
        roots = [(-b + sqrt_d) / (2 * a), (-b - sqrt_d) / (2 * a)]
        if abs(roots[0] - roots[1]) < 1e-9:
            roots = [roots[0]]
        steps.append(f"x = (-b ± sqrt(D)) / 2a -> {', '.join(_format_number(r) for r in roots)}")
        return roots, steps

    steps.append(f"Polynomial degree {degree}; solving numerically.")
    return _numeric_roots(poly.evaluate), steps


_MAX_NUMERIC_ROOTS = 10


def _numeric_roots(f) -> List[float]:
    """Bisection + Newton refinement over progressively wider scans for real roots."""
    roots: List[float] = []
    # Start with the human-scale range, widen only if nothing was found.
    for lo, hi, step in (
        (-1000.0, 1000.0, 1.0),
        (-100000.0, 100000.0, 50.0),
        (-1000000.0, 1000000.0, 500.0),
    ):
        candidates = _scan_brackets(f, lo, hi, step)
        for a, b in candidates:
            try:
                fa, fb = f(a), f(b)
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            # Both endpoints huge with a sign flip usually means an asymptote
            # (e.g. 1/x), not a root — discard those brackets.
            if abs(fa) > 1e8 and abs(fb) > 1e8:
                continue
            try:
                root = _bisect(f, a, b)
            except MathError:
                continue
            root = _newton_refine(f, root)
            try:
                residual = abs(f(root))
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            if residual > 1e-5:
                continue
            if not any(abs(root - existing) < 1e-4 for existing in roots):
                roots.append(root)
                if len(roots) >= _MAX_NUMERIC_ROOTS:
                    return roots
    return roots


def _scan_brackets(f, lo: float, hi: float, step: float) -> List[Tuple[float, float]]:
    """Find sign-change brackets for f over [lo, hi] at the given step."""
    candidates: List[Tuple[float, float]] = []
    x = lo
    try:
        prev = f(x)
    except (ValueError, ZeroDivisionError, OverflowError):
        prev = None
    while x < hi:
        x += step
        try:
            current = f(x)
        except (ValueError, ZeroDivisionError, OverflowError):
            prev = current = None
            continue
        if prev is not None and current is not None and prev * current <= 0:
            candidates.append((x - step, x))
        prev = current
    return candidates


def _bisect(f, a: float, b: float, iterations: int = 200) -> float:
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        raise MathError("No sign change in bracket.")
    for _ in range(iterations):
        mid = (a + b) / 2
        fm = f(mid)
        if abs(fm) < 1e-12 or (b - a) < 1e-12:
            return mid
        if fa * fm <= 0:
            b, fb = mid, fm
        else:
            a, fa = mid, fm
    return (a + b) / 2


def _newton_refine(f, guess: float, iterations: int = 20) -> float:
    h = 1e-6
    x = guess
    for _ in range(iterations):
        fx = f(x)
        fpx = (f(x + h) - f(x - h)) / (2 * h)
        if abs(fpx) < 1e-12:
            break
        x = x - fx / fpx
        if abs(fx) < 1e-12:
            break
    return x


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve(equation: str) -> Dict[str, Any]:
    """Solve an equation in x, e.g. '2x + 3 = 11' or 'x^2 - 5x + 6 = 0'.

    Returns a dict with 'solutions', 'steps', and 'method'.
    """
    equation = (equation or "").strip()
    if not equation:
        raise MathError("Empty equation.")

    # Split on '=' (tolerating '==').
    cleaned = equation.replace("==", "=")
    if "=" in cleaned:
        left_raw, right_raw = cleaned.split("=", 1)
        left_raw, right_raw = left_raw.strip(), right_raw.strip()
        if not left_raw or not right_raw:
            raise MathError("Equation must have both sides.")
    else:
        left_raw, right_raw = cleaned, "0"

    try:
        left_tree = ast.parse(_normalize(left_raw), mode="eval")
        right_tree = ast.parse(_normalize(right_raw), mode="eval")
    except SyntaxError as error:
        raise MathError(f"Could not parse equation: {error}")

    left_poly = _collect_polynomial(left_tree.body)
    right_poly = _collect_polynomial(right_tree.body)

    if left_poly is not None and right_poly is not None:
        difference = left_poly - right_poly
        solutions, steps = _solve_polynomial(difference)
        method = "exact" if steps and ("Linear" in steps[0] or "Quadratic" in steps[0]) else "numeric"
        return {
            "equation": equation,
            "normalized": f"{left_raw} = {right_raw}",
            "solutions": [_format_number(s) for s in solutions],
            "steps": steps,
            "method": method,
        }

    # Non-polynomial: solve f(x) = 0 numerically. The AST is parsed once and
    # reused for every evaluation so the scan stays fast.
    def f(x: float) -> float:
        evaluator = _Evaluator({"x": x})
        return evaluator.visit(left_tree) - evaluator.visit(right_tree)

    roots = _numeric_roots(f)
    return {
        "equation": equation,
        "normalized": f"{left_raw} = {right_raw}",
        "solutions": [_format_number(s) for s in roots],
        "steps": ["Non-polynomial equation; solved numerically with bisection + Newton refinement."],
        "method": "numeric",
        "truncated": len(roots) >= _MAX_NUMERIC_ROOTS,
    }


def solve_math(expression: str) -> str:
    """Human-facing handler: evaluate an expression or solve an equation."""
    expression = (expression or "").strip()
    if not expression:
        return "Usage: provide a math expression (e.g. 'sqrt(144) + 2^5') or an equation (e.g. '2x + 3 = 11')."

    try:
        result = evaluate(expression)
        return (
            f"Expression: {expression}\n"
            f"Result: {_format_number(result)}"
        )
    except MathError:
        pass

    try:
        solved = solve(expression)
    except MathError as error:
        return f"Could not interpret '{expression}' as math: {error}"

    if not solved["solutions"]:
        return (
            f"Equation: {solved['equation']}\n"
            + "\n".join(f"  {step}" for step in solved["steps"])
            + "\nNo real solutions."
        )
    suffix = ""
    if solved.get("truncated"):
        suffix = "\n(Showing the first 10 roots.)"
    return (
        f"Equation: {solved['equation']}\n"
        + "\n".join(f"  {step}" for step in solved["steps"])
        + f"\nSolutions: x = {', '.join(solved['solutions'])}{suffix}"
    )
