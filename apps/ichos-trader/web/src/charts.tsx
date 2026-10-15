// Hand-drawn SVG charts: no chart library, so the page stays small and follows the theme colours.
import { useId } from "react";

type Pt = [number, number];

// A smooth line through the points (Catmull-Rom turned into Bezier curves), like the glass spline.
function smooth(pts: Pt[]): string {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[Math.max(0, i - 1)], [x1, y1] = pts[i], [x2, y2] = pts[i + 1], [x3, y3] = pts[Math.min(pts.length - 1, i + 2)];
    d += ` C${x1 + (x2 - x0) / 6},${y1 + (y2 - y0) / 6} ${x2 - (x3 - x1) / 6},${y2 - (y3 - y1) / 6} ${x2},${y2}`;
  }
  return d;
}

function scale(values: number[], w: number, h: number, pad = 4): Pt[] {
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  return values.map((v, i) => [pad + (i / Math.max(1, values.length - 1)) * (w - 2 * pad), pad + (1 - (v - lo) / span) * (h - 2 * pad)]);
}

export function Spark({ values, up }: { values: number[]; up?: boolean }) {
  if (values.length < 2) return <svg className="spark" />;
  const rising = up ?? values[values.length - 1] >= values[0];
  return (
    <svg className="spark" viewBox="0 0 80 24" preserveAspectRatio="none" aria-hidden>
      <path d={smooth(scale(values, 80, 24, 2))} className={rising ? "line up" : "line down"} />
    </svg>
  );
}

export function Area({ values, labels, height = 180, mark }: { values: number[]; labels?: string[]; height?: number; mark?: string }) {
  const id = useId();
  const w = 600;
  if (values.length < 2) return <div className="empty" style={{ height }}>The chart fills in as the trader runs.</div>;
  const pts = scale(values, w, height, 10);
  const line = smooth(pts);
  const top = pts.reduce((a, b) => (b[1] < a[1] ? b : a));
  const lo = Math.min(...values), hi = Math.max(...values);
  return (
    <svg className="area" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label={`From ${lo.toFixed(0)} to ${hi.toFixed(0)}`}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2={w} y1={height * f} y2={height * f} className="grid" />)}
      <path d={`${line} L${pts[pts.length - 1][0]},${height} L${pts[0][0]},${height} Z`} fill={`url(#${id})`} />
      <path d={line} className="line accent" vectorEffect="non-scaling-stroke" />
      <circle cx={top[0]} cy={top[1]} r="4" className="dot" />
      {mark && <text x={Math.min(top[0], w - 90)} y={Math.max(14, top[1] - 10)} className="tag">{mark}</text>}
      {labels && labels.length > 1 && (
        <>
          <text x="4" y={height - 4} className="axis">{labels[0]}</text>
          <text x={w - 4} y={height - 4} className="axis end">{labels[labels.length - 1]}</text>
        </>
      )}
    </svg>
  );
}

export function Bars({ items, unit = "" }: { items: { label: string; value: number; hint?: string }[]; unit?: string }) {
  const max = Math.max(1, ...items.map((i) => Math.abs(i.value)));
  return (
    <div className="bars">
      {items.map((i) => (
        <div key={i.label} className="bar" title={i.hint ?? `${i.label}: ${i.value.toFixed(1)}${unit}`}>
          <div className="fill" style={{ height: `${Math.max(3, (Math.abs(i.value) / max) * 100)}%` }} />
          <span>{i.label}</span>
        </div>
      ))}
    </div>
  );
}

export function Donut({ parts, size = 120, label }: { parts: { name: string; value: number; color: string }[]; size?: number; label?: string }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const r = size / 2 - 10, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="donut" role="img" aria-label={label}>
      <circle cx={size / 2} cy={size / 2} r={r} className="track" />
      {parts.filter((p) => p.value > 0).map((p) => {
        const len = (p.value / total) * c;
        const el = <circle key={p.name} cx={size / 2} cy={size / 2} r={r} stroke={p.color} strokeDasharray={`${Math.max(0, len - 3)} ${c}`} strokeDashoffset={-offset} className="seg" />;
        offset += len;
        return el;
      })}
      {label && <text x="50%" y="52%" className="center">{label}</text>}
    </svg>
  );
}

// A half-circle dial for 0..1 values (risk, skeptic): the needle shows auto mode's choice.
export function Dial({ value, auto }: { value: number; auto?: number }) {
  const angle = (v: number) => Math.PI * (1 - Math.min(1, Math.max(0, v)));
  const at = (v: number, r: number) => [60 + r * Math.cos(angle(v)), 60 - r * Math.sin(angle(v))];
  const [x, y] = at(value, 44);
  const arc = (v: number) => { const [ax, ay] = at(v, 48); return `M12,60 A48,48 0 0 1 ${ax},${ay}`; };
  return (
    <svg viewBox="0 0 120 68" className="dial" aria-hidden>
      <path d="M12,60 A48,48 0 0 1 108,60" className="track" />
      <path d={arc(value)} className="value" />
      {auto !== undefined && (() => { const [ax, ay] = at(auto, 54); return <circle cx={ax} cy={ay} r="3" className="auto" />; })()}
      <line x1="60" y1="60" x2={x} y2={y} className="needle" />
      <circle cx="60" cy="60" r="4" className="hub" />
    </svg>
  );
}

// Where a prediction's middle path and its likely range sit around zero.
export function Cone({ low, mid, high, span = 6 }: { low: number; mid: number; high: number; span?: number }) {
  const x = (v: number) => 50 + (Math.max(-span, Math.min(span, v)) / span) * 50;
  return (
    <svg viewBox="0 0 100 12" className="cone" preserveAspectRatio="none" aria-hidden>
      <line x1="50" x2="50" y1="0" y2="12" className="zero" />
      <rect x={x(low)} width={Math.max(1, x(high) - x(low))} y="3" height="6" rx="3" className="band" />
      <circle cx={x(mid)} cy="6" r="2.6" className={mid >= 0 ? "mid up" : "mid down"} />
    </svg>
  );
}
