/** Graph boxes in chat (Request H10): a ```chart block is a data spec that draws as an SVG chart.
 *
 * Invariant 2 — specs are data, never code. Two shapes are accepted and validated:
 *
 *   {"type": "line" | "bar" | "scatter" | "area", "title", "x": [..], "series": [{"name", "values": [..]}],
 *    "xLabel", "yLabel"}
 *   {"type": "function", "title", "expressions": ["sin(x)", "x^2/10"], "from": -10, "to": 10}
 *
 * Function plots use a small arithmetic parser (numbers, x, + − × ÷ ^, parentheses, pi, e and
 * sin cos tan asin acos atan sqrt abs log ln exp floor ceil round). Nothing is ever evaluated as
 * JavaScript. Series are told apart by colour *and* by marker shape and dash, and the numbers are
 * available as a table under the chart.
 */

import { useMemo, useState } from "react";

interface Series { name: string; values: number[] }
interface Spec {
  type: "line" | "bar" | "scatter" | "area" | "function";
  title?: string;
  x: (string | number)[];
  series: Series[];
  xLabel?: string;
  yLabel?: string;
}

// Dark-surface palette; each ≥ 4.5:1 on #0E0E13 and paired with a distinct marker and dash.
const COLORS = ["#8B7CFF", "#4CC9F0", "#F9A23B", "#5EE08F", "#FF7A8A", "#E6E15C"];
const DASHES = ["", "6 4", "2 3", "10 4 2 4", "4 4", "1 3"];
const MARKERS = ["circle", "square", "triangle", "diamond", "circle", "square"] as const;

// --- a safe arithmetic parser ------------------------------------------------------------

type Node = { k: "num"; v: number } | { k: "x" } | { k: "neg"; a: Node } | { k: "bin"; op: string; a: Node; b: Node } | { k: "fn"; name: string; a: Node };
const FUNCS: Record<string, (v: number) => number> = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan, sqrt: Math.sqrt,
  abs: Math.abs, log: Math.log10, ln: Math.log, exp: Math.exp, floor: Math.floor, ceil: Math.ceil, round: Math.round,
};

export function parseExpression(source: string): Node {
  const text = source.replace(/\s+/g, "").replace(/\*\*/g, "^").toLowerCase();
  let i = 0;
  const peek = () => text[i];
  function primary(): Node {
    const ch = peek();
    if (ch === "(") { i += 1; const inner = sum(); if (peek() !== ")") throw new Error("missing )"); i += 1; return inner; }
    if (ch === "-") { i += 1; return { k: "neg", a: power() }; }
    if (ch === "+") { i += 1; return power(); }
    const num = text.slice(i).match(/^\d+(\.\d+)?|^\.\d+/);
    if (num) { i += num[0].length; return { k: "num", v: parseFloat(num[0]) }; }
    const word = text.slice(i).match(/^[a-z]+/);
    if (word) {
      const name = word[0];
      i += name.length;
      if (name === "x") return { k: "x" };
      if (name === "pi") return { k: "num", v: Math.PI };
      if (name === "e") return { k: "num", v: Math.E };
      if (FUNCS[name] && peek() === "(") return { k: "fn", name, a: primary() };
      throw new Error(`unknown word ${name}`);
    }
    throw new Error(`unexpected ${ch ?? "end"}`);
  }
  function power(): Node {
    const base = implicit();
    if (peek() === "^") { i += 1; return { k: "bin", op: "^", a: base, b: power() }; }
    return base;
  }
  function implicit(): Node {
    let node = primary();
    // 2x, 3(x+1), x(x-1)
    while (peek() && /[a-z(]/.test(peek()!) && text.slice(i, i + 1) !== ")") node = { k: "bin", op: "*", a: node, b: primary() };
    return node;
  }
  function product(): Node {
    let node = power();
    while (peek() === "*" || peek() === "/") { const op = text[i]; i += 1; node = { k: "bin", op, a: node, b: power() }; }
    return node;
  }
  function sum(): Node {
    let node = product();
    while (peek() === "+" || peek() === "-") { const op = text[i]; i += 1; node = { k: "bin", op, a: node, b: product() }; }
    return node;
  }
  const tree = sum();
  if (i !== text.length) throw new Error(`unexpected ${text[i]}`);
  return tree;
}

export function evaluate(node: Node, x: number): number {
  switch (node.k) {
    case "num": return node.v;
    case "x": return x;
    case "neg": return -evaluate(node.a, x);
    case "fn": return FUNCS[node.name](evaluate(node.a, x));
    case "bin": {
      const a = evaluate(node.a, x), b = evaluate(node.b, x);
      return node.op === "+" ? a + b : node.op === "-" ? a - b : node.op === "*" ? a * b : node.op === "/" ? a / b : Math.pow(a, b);
    }
  }
}

// --- spec validation ----------------------------------------------------------------------

export function readSpec(source: string): Spec {
  const raw = JSON.parse(source) as Record<string, unknown>;
  const type = String(raw.type ?? "line") as Spec["type"];
  if (!["line", "bar", "scatter", "area", "function"].includes(type)) throw new Error(`unknown chart type "${type}"`);
  const title = typeof raw.title === "string" ? raw.title.slice(0, 120) : undefined;
  if (type === "function") {
    const expressions = (Array.isArray(raw.expressions) ? raw.expressions : [raw.expression]).filter((e): e is string => typeof e === "string").slice(0, 6);
    if (expressions.length === 0) throw new Error("a function chart needs expressions");
    const from = Number(raw.from ?? -10), to = Number(raw.to ?? 10);
    if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to) throw new Error("from must be less than to");
    const steps = 240;
    const xs = Array.from({ length: steps + 1 }, (_, n) => from + ((to - from) * n) / steps);
    const series = expressions.map((expression) => {
      const tree = parseExpression(expression);
      return { name: `y = ${expression}`, values: xs.map((x) => evaluate(tree, x)) };
    });
    return { type: "line", title, x: xs, series, xLabel: "x", yLabel: "y" };
  }
  const x = Array.isArray(raw.x) ? raw.x.slice(0, 500).map((v) => (typeof v === "number" ? v : String(v))) : [];
  const series = (Array.isArray(raw.series) ? raw.series : []).slice(0, 6).map((s, n) => {
    const item = s as Record<string, unknown>;
    return { name: typeof item.name === "string" ? item.name.slice(0, 60) : `Series ${n + 1}`, values: (Array.isArray(item.values) ? item.values : []).slice(0, 500).map(Number) };
  }).filter((s) => s.values.length > 0);
  if (series.length === 0) throw new Error("the chart has no series with values");
  const length = Math.max(...series.map((s) => s.values.length));
  return { type, title, x: x.length ? x : Array.from({ length }, (_, n) => n + 1), series,
    xLabel: typeof raw.xLabel === "string" ? raw.xLabel.slice(0, 60) : undefined, yLabel: typeof raw.yLabel === "string" ? raw.yLabel.slice(0, 60) : undefined };
}

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? mag * 10;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

const fmt = (v: number) => (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(1) : String(Number(v.toFixed(3))));

function Marker({ shape, x, y, color }: { shape: (typeof MARKERS)[number]; x: number; y: number; color: string }) {
  if (shape === "square") return <rect x={x - 3} y={y - 3} width={6} height={6} fill={color} />;
  if (shape === "triangle") return <path d={`M${x},${y - 4} L${x + 4},${y + 3} L${x - 4},${y + 3} Z`} fill={color} />;
  if (shape === "diamond") return <path d={`M${x},${y - 4} L${x + 4},${y} L${x},${y + 4} L${x - 4},${y} Z`} fill={color} />;
  return <circle cx={x} cy={y} r={3.2} fill={color} />;
}

export function ChartBox({ source }: { source: string }) {
  const [showTable, setShowTable] = useState(false);
  const parsed = useMemo(() => {
    try { return { spec: readSpec(source), error: "" }; } catch (error) { return { spec: null, error: (error as Error).message }; }
  }, [source]);

  if (!parsed.spec) {
    return <div className="chart-box chart-box--error" role="note">This chart could not be drawn: {parsed.error}.</div>;
  }
  const spec = parsed.spec;
  const W = 640, H = 320, L = 52, R = 16, T = spec.title ? 34 : 14, B = 44;
  const all = spec.series.flatMap((s) => s.values).filter(Number.isFinite);
  const yMin = Math.min(spec.type === "bar" || spec.type === "area" ? 0 : Infinity, ...all);
  const yMax = Math.max(spec.type === "bar" ? 0 : -Infinity, ...all);
  const yTicks = niceTicks(yMin, yMax);
  const lo = Math.min(yTicks[0], yMin), hi = Math.max(yTicks[yTicks.length - 1], yMax);
  const numericX = spec.x.every((v) => typeof v === "number") && spec.type !== "bar";
  const xs = spec.x as number[];
  const xMin = numericX ? Math.min(...xs) : 0, xMax = numericX ? Math.max(...xs) : Math.max(1, spec.x.length - 1);
  const px = (index: number) => {
    if (spec.type === "bar") return L + ((index + 0.5) * (W - L - R)) / spec.x.length;
    const value = numericX ? xs[index] : index;
    return L + ((value - xMin) / (xMax - xMin || 1)) * (W - L - R);
  };
  const py = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const xTicks = numericX ? niceTicks(xMin, xMax, 6) : spec.x.map((_, n) => n).filter((n) => spec.x.length <= 12 || n % Math.ceil(spec.x.length / 10) === 0);
  const description = `${spec.title ?? "Chart"}: ${spec.series.map((s) => s.name).join(", ")} across ${spec.x.length} points`;

  return (
    <figure className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={description} className="chart-box__svg">
        {spec.title && <text x={L} y={20} className="chart-box__title">{spec.title}</text>}
        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line x1={L} x2={W - R} y1={py(tick)} y2={py(tick)} className={tick === 0 ? "chart-box__zero" : "chart-box__grid"} />
            <text x={L - 6} y={py(tick) + 4} textAnchor="end" className="chart-box__tick">{fmt(tick)}</text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text key={`x${tick}`} x={numericX ? L + ((tick - xMin) / (xMax - xMin || 1)) * (W - L - R) : px(tick)} y={H - B + 16} textAnchor="middle" className="chart-box__tick">
            {numericX ? fmt(tick) : String(spec.x[tick]).slice(0, 10)}
          </text>
        ))}
        {spec.xLabel && <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" className="chart-box__axis">{spec.xLabel}</text>}
        {spec.yLabel && <text x={12} y={(T + H - B) / 2} textAnchor="middle" transform={`rotate(-90 12 ${(T + H - B) / 2})`} className="chart-box__axis">{spec.yLabel}</text>}

        {spec.series.map((series, s) => {
          const color = COLORS[s % COLORS.length];
          if (spec.type === "bar") {
            const band = (W - L - R) / spec.x.length;
            const width = Math.max(2, (band * 0.8) / spec.series.length);
            return (
              <g key={series.name}>
                {series.values.map((v, n) => Number.isFinite(v) && (
                  <rect key={n} x={px(n) - (band * 0.8) / 2 + s * width} y={Math.min(py(v), py(0))} width={width - 1} height={Math.abs(py(v) - py(0))}
                    fill={color} opacity={0.9} />
                ))}
              </g>
            );
          }
          const segments: string[] = [];
          let current = "";
          series.values.forEach((v, n) => {
            const ok = Number.isFinite(v) && Math.abs(v) < 1e12;
            if (!ok) { if (current) segments.push(current); current = ""; return; }
            current += `${current ? "L" : "M"}${px(n).toFixed(1)},${py(Math.max(lo, Math.min(hi, v))).toFixed(1)}`;
          });
          if (current) segments.push(current);
          const showMarkers = spec.type === "scatter" || series.values.length <= 40;
          return (
            <g key={series.name}>
              {spec.type === "area" && segments.map((d, n) => <path key={`a${n}`} d={`${d} L${W - R},${py(lo)} L${L},${py(lo)} Z`} fill={color} opacity={0.14} />)}
              {spec.type !== "scatter" && segments.map((d, n) => (
                <path key={n} d={d} fill="none" stroke={color} strokeWidth={2} strokeDasharray={DASHES[s % DASHES.length]} strokeLinejoin="round" />
              ))}
              {showMarkers && series.values.map((v, n) => Number.isFinite(v) && (
                <Marker key={`m${n}`} shape={MARKERS[s % MARKERS.length]} x={px(n)} y={py(v)} color={color} />
              ))}
            </g>
          );
        })}
      </svg>
      <figcaption className="chart-box__legend">
        {spec.series.map((series, s) => (
          <span key={series.name} className="chart-box__key">
            <svg width="26" height="10" aria-hidden="true">
              <line x1="1" x2="25" y1="5" y2="5" stroke={COLORS[s % COLORS.length]} strokeWidth="2" strokeDasharray={spec.type === "bar" ? "" : DASHES[s % DASHES.length]} />
              <Marker shape={MARKERS[s % MARKERS.length]} x={13} y={5} color={COLORS[s % COLORS.length]} />
            </svg>
            {series.name}
          </span>
        ))}
        <button type="button" className="chat-inline chart-box__table-toggle" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Hide numbers" : "Show numbers"}
        </button>
      </figcaption>
      {showTable && (
        <div className="chart-box__table">
          <table>
            <thead><tr><th scope="col">{spec.xLabel ?? "x"}</th>{spec.series.map((s) => <th key={s.name} scope="col">{s.name}</th>)}</tr></thead>
            <tbody>
              {spec.x.slice(0, 200).map((x, n) => (
                <tr key={n}><th scope="row">{typeof x === "number" ? fmt(x) : x}</th>{spec.series.map((s) => <td key={s.name}>{Number.isFinite(s.values[n]) ? fmt(s.values[n]) : "—"}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}
