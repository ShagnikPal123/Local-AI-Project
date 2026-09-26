"""Tables for Data Process Use: reading them, profiling them, and running declarative operations on them (Request R7).

The owner wants to "analyze data like a resume or group of resume or a code or spread sheet or whatever … explain
what's in it, sort, or do whatever the user wants … Even financial analyzers can use this."

A model decides *what* to compute; this module computes it. The model's plan is data — a list of operations such as
``{"op": "filter", "where": [{"col": "amount", "cmp": ">", "value": 1000}]}`` — and every operation is implemented here.
Formulas (``derive``) go through a whitelist parser built on ``ast``: numbers, column names, arithmetic and a few
functions, nothing else. No model-written code ever runs (AGENTS.md §7).
"""

from __future__ import annotations

import ast
import csv
import io
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MAX_ROWS = 50_000
SHOW_ROWS = 400

Row = Dict[str, Any]


class TableError(ValueError):
    """An operation that cannot run on this table; the message names the column or value at fault."""


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"^\(?[-+]?[$€£¥₹]?\s*[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|[kKmMbB])?\)?$")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def to_number(value: Any) -> Optional[float]:
    """"$1,234.50" → 1234.5, "(120)" → -120, "12%" → 12, "3.4k" → 3400. ``None`` when it is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value or "").strip()
    if not text or not _NUMBER.match(text):
        return None
    negative = text.startswith("(") and text.endswith(")")
    clean = re.sub(r"[()$€£¥₹,%\s]", "", text)
    scale = 1.0
    if clean[-1:].lower() in ("k", "m", "b"):
        scale = {"k": 1e3, "m": 1e6, "b": 1e9}[clean[-1].lower()]
        clean = clean[:-1]
    try:
        number = float(clean) * scale
    except ValueError:
        return None
    return -abs(number) if negative else number


def to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text or len(text) > 40:
        return None
    candidates = [text, text.split("T")[0], text.split(" ")[0]]
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%Y-%m", "%b %Y", "%B %Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        for candidate in candidates:
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                continue
    match = re.match(r"^(\d{4})$", text)
    if match and 1900 <= int(match.group(1)) <= 2100:
        return date(int(match.group(1)), 1, 1)
    match = re.match(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{4})$", text)
    if match and match.group(1).lower() in _MONTHS:
        return date(int(match.group(2)), _MONTHS[match.group(1).lower()], 1)
    return None


def column_type(values: Sequence[Any]) -> str:
    present = [v for v in values if str(v if v is not None else "").strip() != ""]
    if not present:
        return "empty"
    sample = present[:400]
    numbers = sum(1 for v in sample if to_number(v) is not None)
    if numbers / len(sample) >= 0.85:
        return "number"
    dates = sum(1 for v in sample if to_date(v) is not None)
    if dates / len(sample) >= 0.85:
        return "date"
    lowered = {str(v).strip().lower() for v in sample}
    if lowered <= {"true", "false", "yes", "no", "y", "n", "0", "1"}:
        return "bool"
    return "text"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _header(cells: Sequence[str]) -> List[str]:
    names: List[str] = []
    for index, cell in enumerate(cells):
        name = re.sub(r"\s+", " ", str(cell or "").strip())[:60] or f"column {index + 1}"
        base, n = name, 2
        while name in names:
            name, n = f"{base} {n}", n + 1
        names.append(name)
    return names


def _looks_like_header(first: Sequence[str], second: Sequence[str]) -> bool:
    if not first:
        return False
    numeric_first = sum(1 for c in first if to_number(c) is not None)
    numeric_second = sum(1 for c in second if to_number(c) is not None) if second else 0
    return numeric_first == 0 or numeric_first < numeric_second


def table_from_rows(raw: List[List[str]], name: str = "table") -> Dict[str, Any]:
    raw = [row for row in raw if any(str(c).strip() for c in row)][: MAX_ROWS + 1]
    if not raw:
        raise TableError(f"{name} has no rows.")
    width = max(len(r) for r in raw)
    raw = [list(r) + [""] * (width - len(r)) for r in raw]
    if _looks_like_header(raw[0], raw[1] if len(raw) > 1 else []):
        columns, body = _header(raw[0]), raw[1:]
    else:
        columns, body = [f"column {i + 1}" for i in range(width)], raw
    rows = [{columns[i]: (cell.strip() if isinstance(cell, str) else cell) for i, cell in enumerate(r)} for r in body]
    return {"name": name, "columns": columns, "rows": rows}


def read_csv(text: str, name: str = "table") -> Dict[str, Any]:
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel_tab if sample.count("\t") > sample.count(",") else csv.excel
    return table_from_rows(list(csv.reader(io.StringIO(text), dialect)), name)


def looks_tabular(text: str) -> bool:
    """Is this pasted text really a table? Rows that share a delimiter count are a spreadsheet, not prose."""
    lines = [line for line in (text or "").splitlines() if line.strip()][:200]
    if len(lines) < 2:
        return False
    for delimiter in (",", "\t", ";", "|"):
        counts = [line.count(delimiter) for line in lines]
        common = Counter(counts).most_common(1)[0]
        if common[0] >= 1 and common[1] >= max(2, len(lines) * 0.8):
            return True
    return False


def read_sheets(text: str, name: str = "workbook") -> List[Dict[str, Any]]:
    """The tab-separated dump ``uploads.extract_document_text`` makes of an .xlsx: one table per sheet."""
    tables = []
    parts = re.split(r"^--- (.+?) ---$", text, flags=re.M)
    for index in range(1, len(parts) - 1, 2):
        sheet, body = parts[index].strip(), parts[index + 1]
        rows = [line.split("\t") for line in body.splitlines() if line.strip()]
        if rows:
            try:
                tables.append(table_from_rows(rows, f"{name} · {sheet}"))
            except TableError:
                continue
    return tables


def read_json(text: str, name: str = "table") -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
    if not (isinstance(data, list) and data and isinstance(data[0], dict)):
        return None
    columns: List[str] = []
    for item in data[:2000]:
        for key in item:
            if key not in columns:
                columns.append(str(key))
    rows = [{c: (json.dumps(item.get(c)) if isinstance(item.get(c), (dict, list)) else item.get(c)) for c in columns}
            for item in data[:MAX_ROWS] if isinstance(item, dict)]
    return {"name": name, "columns": columns, "rows": rows}


def markdown_tables(text: str, name: str = "table") -> List[Dict[str, Any]]:
    tables = []
    for block in re.findall(r"((?:^\|.*\|\s*$\n?){3,})", text or "", flags=re.M):
        lines = [l.strip().strip("|") for l in block.strip().splitlines()]
        rows = [[c.strip() for c in l.split("|")] for l in lines if not re.match(r"^[\s:|-]+$", l)]
        if len(rows) >= 2:
            try:
                tables.append(table_from_rows(rows, f"{name} table {len(tables) + 1}"))
            except TableError:
                continue
    return tables


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _numbers(rows: Sequence[Row], col: str) -> List[float]:
    return [n for n in (to_number(r.get(col)) for r in rows) if n is not None]


def _quartiles(values: List[float]) -> Tuple[float, float]:
    ordered = sorted(values)
    if len(ordered) < 4:
        return ordered[0], ordered[-1]
    q = statistics.quantiles(ordered, n=4)
    return q[0], q[2]


def profile(table: Dict[str, Any]) -> Dict[str, Any]:
    rows, columns = table["rows"], table["columns"]
    out: List[Dict[str, Any]] = []
    for col in columns:
        values = [r.get(col) for r in rows]
        kind = column_type(values)
        missing = sum(1 for v in values if str(v if v is not None else "").strip() == "")
        entry: Dict[str, Any] = {"name": col, "type": kind, "missing": missing, "unique": len({str(v) for v in values})}
        if kind == "number":
            nums = _numbers(rows, col)
            if nums:
                low, high = _quartiles(nums)
                spread = high - low
                outliers = [n for n in nums if spread and (n < low - 1.5 * spread or n > high + 1.5 * spread)]
                entry.update(min=min(nums), max=max(nums), sum=round(sum(nums), 4), mean=round(statistics.fmean(nums), 4),
                             median=statistics.median(nums), std=round(statistics.pstdev(nums), 4) if len(nums) > 1 else 0.0,
                             outliers=len(outliers))
        elif kind == "date":
            dates = [d for d in (to_date(v) for v in values) if d]
            if dates:
                entry.update(first=min(dates).isoformat(), last=max(dates).isoformat())
        else:
            top = Counter(str(v).strip() for v in values if str(v or "").strip()).most_common(5)
            entry["top"] = [{"value": v[:60], "count": n} for v, n in top]
        out.append(entry)
    numeric = [c["name"] for c in out if c["type"] == "number"]
    correlations = []
    for i, a in enumerate(numeric[:12]):
        for b in numeric[i + 1:12]:
            value = correlation(rows, a, b)
            if value is not None and abs(value) >= 0.5:
                correlations.append({"a": a, "b": b, "r": round(value, 3)})
    correlations.sort(key=lambda c: -abs(c["r"]))
    return {"name": table["name"], "rows": len(rows), "columns": out, "correlations": correlations[:8]}


def correlation(rows: Sequence[Row], a: str, b: str) -> Optional[float]:
    pairs = [(to_number(r.get(a)), to_number(r.get(b))) for r in rows]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy)


# ---------------------------------------------------------------------------
# Safe formulas
# ---------------------------------------------------------------------------

_FUNCTIONS: Dict[str, Callable[..., float]] = {
    "abs": abs, "round": lambda x, n=0: round(x, int(n)), "min": min, "max": max, "sqrt": math.sqrt, "log": math.log,
    "log10": math.log10, "exp": math.exp, "pow": pow,
}
_OPERATORS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
              ast.Div: lambda a, b: a / b if b else None, ast.Pow: lambda a, b: a ** b if abs(b) <= 8 else None,
              ast.Mod: lambda a, b: a % b if b else None}


def _identifier(name: str) -> str:
    return re.sub(r"\W+", "_", name.strip().lower()).strip("_") or "col"


def compile_formula(expr: str, columns: Sequence[str]) -> Callable[[Row], Optional[float]]:
    """``"(revenue - cost) / revenue"`` → a function of a row. Column names may be written with underscores for spaces,
    or in backticks. Anything but arithmetic, numbers, known columns and the listed functions is refused."""
    names = {_identifier(c): c for c in columns}
    text = re.sub(r"`([^`]+)`", lambda m: _identifier(m.group(1)), str(expr or ""))
    if len(text) > 300:
        raise TableError("That formula is too long.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as error:
        raise TableError(f"Could not read the formula “{expr}”.") from error

    def check(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            check(node.operand)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        elif isinstance(node, ast.Name):
            if node.id not in names:
                raise TableError(f"No column called “{node.id}”. Columns: {', '.join(columns[:12])}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            for arg in node.args:
                check(arg)
        else:
            raise TableError(f"Formulas can use numbers, columns, + − × ÷ ^ and {', '.join(_FUNCTIONS)} — not “{ast.dump(node)[:40]}”.")

    check(tree)

    def evaluate(node: ast.AST, row: Row) -> Optional[float]:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, row)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return to_number(row.get(names[node.id]))
        if isinstance(node, ast.UnaryOp):
            value = evaluate(node.operand, row)
            return None if value is None else (-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left, row), evaluate(node.right, row)
            if left is None or right is None:
                return None
            try:
                return _OPERATORS[type(node.op)](left, right)
            except (OverflowError, ValueError, ZeroDivisionError):
                return None
        if isinstance(node, ast.Call):
            args = [evaluate(arg, row) for arg in node.args]
            if any(a is None for a in args):
                return None
            try:
                return float(_FUNCTIONS[node.func.id](*args))
            except (OverflowError, ValueError, TypeError, ZeroDivisionError):
                return None
        return None

    return lambda row: evaluate(tree, row)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _column(table: Dict[str, Any], name: Any) -> str:
    wanted = str(name or "").strip()
    for col in table["columns"]:
        if col == wanted:
            return col
    lowered = wanted.lower().replace("_", " ")
    for col in table["columns"]:
        if col.lower() == lowered:
            return col
    for col in table["columns"]:
        if lowered and (lowered in col.lower() or col.lower() in lowered):
            return col
    # A model often writes a computed column its own way ("units_sum" for "sum of units"): same words, any order.
    def words(name: str) -> frozenset:
        return frozenset(w for w in re.split(r"[^a-z0-9]+", name.lower()) if w and w not in ("of", "the", "per", "by"))
    wanted_words = words(wanted)
    if wanted_words:
        for col in table["columns"]:
            if words(col) == wanted_words:
                return col
        for col in table["columns"]:
            if wanted_words <= words(col) or words(col) <= wanted_words:
                return col
    raise TableError(f"No column called “{wanted}”. Columns: {', '.join(table['columns'][:15])}")


def _compare(value: Any, cmp: str, target: Any) -> bool:
    if cmp in ("missing", "not_missing"):
        empty = str(value if value is not None else "").strip() == ""
        return empty if cmp == "missing" else not empty
    number, goal = to_number(value), to_number(target)
    if cmp in (">", ">=", "<", "<=") :
        if number is None or goal is None:
            first, second = to_date(value), to_date(target)
            if first is None or second is None:
                return False
            number, goal = first.toordinal(), second.toordinal()
        return {">": number > goal, ">=": number >= goal, "<": number < goal, "<=": number <= goal}[cmp]
    text, wanted = str(value if value is not None else "").strip().lower(), str(target if target is not None else "").strip().lower()
    if cmp in ("=", "=="):
        return (number == goal) if number is not None and goal is not None else text == wanted
    if cmp == "!=":
        return (number != goal) if number is not None and goal is not None else text != wanted
    if cmp == "contains":
        return wanted in text
    if cmp == "not_contains":
        return wanted not in text
    if cmp == "starts":
        return text.startswith(wanted)
    if cmp == "in":
        options = target if isinstance(target, list) else str(target).split(",")
        return text in {str(o).strip().lower() for o in options}
    raise TableError(f"Unknown comparison “{cmp}”.")


def _aggregate(values: List[Any], fn: str) -> Any:
    nums = [n for n in (to_number(v) for v in values) if n is not None]
    if fn == "count":
        return len([v for v in values if str(v if v is not None else "").strip() != ""])
    if fn == "unique":
        return len({str(v) for v in values})
    if not nums:
        return None
    return {"sum": lambda: round(sum(nums), 4), "mean": lambda: round(statistics.fmean(nums), 4), "median": lambda: statistics.median(nums),
            "min": lambda: min(nums), "max": lambda: max(nums), "std": lambda: round(statistics.pstdev(nums), 4) if len(nums) > 1 else 0.0,
            }.get(fn, lambda: None)()


def run_operations(table: Dict[str, Any], operations: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    """Apply a plan to a copy of the table. Returns the result and one plain sentence per step (for the log)."""
    current = {"name": table["name"], "columns": list(table["columns"]), "rows": [dict(r) for r in table["rows"]]}
    notes: List[str] = []
    for step in list(operations)[:20]:
        if not isinstance(step, dict):
            continue
        op = str(step.get("op", "")).lower()
        before = len(current["rows"])
        if op == "filter":
            conditions = [(_column(current, c.get("col")), str(c.get("cmp", "=")), c.get("value")) for c in step.get("where") or []]
            joiner = any if step.get("any") else all
            current["rows"] = [r for r in current["rows"] if joiner(_compare(r.get(col), cmp, value) for col, cmp, value in conditions)]
            notes.append(f"Kept {len(current['rows'])} of {before} rows where " + (" or " if step.get("any") else " and ").join(
                f"{col} {cmp} {value}" for col, cmp, value in conditions))
        elif op == "sort":
            for key in reversed(step.get("by") or []):
                col = _column(current, key.get("col"))
                kind = column_type([r.get(col) for r in current["rows"]])
                def sort_key(row: Row, col: str = col, kind: str = kind) -> Tuple[bool, Any]:
                    value = row.get(col)
                    if kind == "number":
                        parsed: Any = to_number(value)
                    elif kind == "date":
                        when = to_date(value)
                        parsed = when.toordinal() if when else None
                    else:
                        parsed = str(value if value is not None else "").strip().lower() or None
                    return (parsed is None, parsed if parsed is not None else 0)
                current["rows"].sort(key=sort_key, reverse=bool(key.get("desc")))
                if key.get("desc"):  # keep blanks last either way
                    current["rows"].sort(key=lambda r, col=col: str(r.get(col) or "").strip() == "")
            notes.append("Sorted by " + ", ".join(f"{k.get('col')}{' (highest first)' if k.get('desc') else ''}" for k in step.get("by") or []))
        elif op == "select":
            cols = [_column(current, c) for c in step.get("cols") or []]
            if cols:
                current["columns"] = cols
                current["rows"] = [{c: r.get(c) for c in cols} for r in current["rows"]]
                notes.append("Columns: " + ", ".join(cols))
        elif op == "derive":
            name = str(step.get("name") or "result")[:40]
            formula = compile_formula(str(step.get("expr", "")), current["columns"])
            for row in current["rows"]:
                value = formula(row)
                row[name] = None if value is None else round(value, 6)
            if name not in current["columns"]:
                current["columns"].append(name)
            notes.append(f"Added {name} = {step.get('expr')}")
        elif op == "group":
            by = [_column(current, c) for c in step.get("by") or []]
            aggs = [(_column(current, a.get("col")) if a.get("col") else None, str(a.get("fn", "count")).lower()) for a in step.get("agg") or [{"fn": "count"}]]
            groups: Dict[Tuple[str, ...], List[Row]] = defaultdict(list)
            for row in current["rows"]:
                groups[tuple(str(row.get(c, "")) for c in by)].append(row)
            columns = list(by) + [f"{fn} of {col}" if col else "count" for col, fn in aggs]
            rows = []
            for key, members in groups.items():
                row = dict(zip(by, key))
                for col, fn in aggs:
                    row[f"{fn} of {col}" if col else "count"] = _aggregate([m.get(col) for m in members] if col else members, fn if col else "count")
                rows.append(row)
            current = {"name": current["name"], "columns": columns, "rows": rows}
            notes.append(f"Grouped {before} rows into {len(rows)} by {', '.join(by) or 'everything'}")
        elif op == "top":
            n = max(1, min(int(step.get("n") or 10), 1000))
            current["rows"] = current["rows"][:n]
            notes.append(f"Top {n}")
        elif op == "describe":
            cols = [_column(current, c) for c in step.get("cols") or []] or current["columns"]
            prof = profile({**current, "columns": cols})
            rows = []
            for entry in prof["columns"]:
                rows.append({"column": entry["name"], "type": entry["type"], "missing": entry["missing"], "unique": entry["unique"],
                             **{k: entry.get(k) for k in ("min", "max", "mean", "median", "std", "sum", "outliers", "first", "last")}})
            current = {"name": f"{current['name']} · summary", "columns": ["column", "type", "missing", "unique", "min", "max", "mean", "median",
                                                                           "std", "sum", "outliers", "first", "last"], "rows": rows}
            notes.append(f"Described {len(cols)} columns")
        elif op == "outliers":
            col = _column(current, step.get("col"))
            nums = _numbers(current["rows"], col)
            if len(nums) >= 4:
                low, high = _quartiles(nums)
                spread = high - low
                current["rows"] = [r for r in current["rows"] if to_number(r.get(col)) is not None and spread
                                   and not (low - 1.5 * spread <= to_number(r.get(col)) <= high + 1.5 * spread)]
            notes.append(f"{len(current['rows'])} unusual values in {col} (outside 1.5× the middle half)")
        elif op == "correlate":
            cols = [_column(current, c) for c in step.get("cols") or []] or [c for c in current["columns"]
                                                                                   if column_type([r.get(c) for r in current["rows"]]) == "number"][:8]
            rows = []
            for i, a in enumerate(cols):
                for b in cols[i + 1:]:
                    r = correlation(current["rows"], a, b)
                    if r is not None:
                        rows.append({"a": a, "b": b, "r": round(r, 3), "strength": "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak"})
            rows.sort(key=lambda x: -abs(x["r"]))
            current = {"name": f"{current['name']} · correlations", "columns": ["a", "b", "r", "strength"], "rows": rows}
            notes.append(f"Correlated {len(cols)} columns")
        elif op == "trend":
            x, y = _column(current, step.get("x")), _column(current, step.get("y"))
            current = {"name": f"{current['name']} · trend", "columns": ["measure", "value"], "rows": trend_rows(current["rows"], x, y)}
            notes.append(f"Trend of {y} over {x}")
        else:
            raise TableError(f"Unknown operation “{op}”.")
    return current, notes


def trend_rows(rows: Sequence[Row], x: str, y: str) -> List[Row]:
    points = []
    for index, row in enumerate(rows):
        value = to_number(row.get(y))
        when = to_date(row.get(x))
        position = when.toordinal() if when else to_number(row.get(x))
        if value is not None:
            points.append((position if position is not None else index, value))
    points.sort()
    if len(points) < 2:
        return [{"measure": "points", "value": len(points)}]
    xs, ys = zip(*points)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((a - mx) ** 2 for a in xs)
    slope = sum((a - mx) * (b - my) for a, b in points) / denominator if denominator else 0.0
    first, last = ys[0], ys[-1]
    change = (last - first) / abs(first) if first else None
    periods = len(points) - 1
    cagr = ((last / first) ** (1 / periods) - 1) if first and last and first > 0 and last > 0 and periods else None
    out = [{"measure": "first", "value": first}, {"measure": "last", "value": last},
           {"measure": "change", "value": round(last - first, 4)},
           {"measure": "change %", "value": round(change * 100, 2) if change is not None else None},
           {"measure": "average growth per step %", "value": round(cagr * 100, 2) if cagr is not None else None},
           {"measure": "slope per step" if not to_date(rows[0].get(x)) else "slope per day", "value": round(slope, 6)},
           {"measure": "highest", "value": max(ys)}, {"measure": "lowest", "value": min(ys)}]
    return out


def preview(table: Dict[str, Any], limit: int = SHOW_ROWS) -> Dict[str, Any]:
    rows = table["rows"][:limit]
    return {"name": table["name"], "columns": table["columns"], "rows": [[_cell(r.get(c)) for c in table["columns"]] for r in rows],
            "total": len(table["rows"]), "shown": len(rows)}


def _cell(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if value is None:
        return ""
    return value if isinstance(value, (int, bool)) else str(value)[:300]


def to_csv(table: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(table["columns"])
    for row in table["rows"]:
        writer.writerow([_cell(row.get(c)) for c in table["columns"]])
    return buffer.getvalue()
