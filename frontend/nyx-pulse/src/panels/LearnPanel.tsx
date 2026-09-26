/** Learn — watch Nyx Core, Nyx's own model, grow.
 *
 * Everything here is measured, not decorative: the level is the count of learned
 * parameters (`/api/core`), the network drawing is the real network with the real
 * activations for whatever you type (`/api/core/network`), accuracy is scored
 * before each turn trains it, and "on its own" is the share of answers that came
 * from Nyx's own memory rather than an API model. Charts follow the dataviz
 * method: one series per plot unless compared, 2px lines, thin bars, a legend for
 * two series, hover tooltips, and a table twin for every chart.
 * Palette (validated on #0e0e13): series #3987e5 (blue), #d95926 (orange).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading } from "../components/Panel";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { useReducedMotion } from "../useReducedMotion";

const SERIES_1 = "#3987e5";
const SERIES_2 = "#d95926";

interface Core {
  level: number; name: string; like: string; parameters: number; next_name: string | null; next_at: number | null; progress: number;
  parts: Record<string, number>; examples: number; widths: number[]; depth: number; network_parameters: number;
  growth_log: { ts: number; event: string; examples: number }[]; loss: number[];
  route_accuracy: number | null; domain_accuracy: number | null; accuracy_curve: number[];
  independence: number; local_answers: number; api_answers: number;
  daily: Record<string, { local: number; api: number; turns: number }>;
  crutches: { domain: string; provider: string; model: string; n: number; ok: number; avg_ms: number; rating: number }[];
}

interface Network {
  layers: { name: string; size: number; activation?: number[]; neurons?: number[]; active?: number[] }[];
  links: { from: [string, number]; to: [string, number]; w: number }[];
  heads: Record<string, { labels: string[]; values: number[] }>;
  parameters: number; examples: number;
}

interface Memory { id: number; text: string; source: string; kind: string; created: number; cluster: number }

const PART_LABELS: Record<string, string> = {
  neural_network: "Neural network", word_model: "Word model", knowledge_graph: "Knowledge graph",
  learner: "Router learner", answer_memory: "Answer memory", distillation_examples: "Training examples",
};

const compact = (n: number) => Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

function TableToggle({ children, label }: { children: React.ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="chat-inline" onClick={() => setOpen((v) => !v)} aria-expanded={open} style={{ fontSize: 12, marginTop: 8 }}>
        {open ? "Hide table" : `Show ${label} as a table`}
      </button>
      {open && <div style={{ marginTop: 8, overflowX: "auto" }}>{children}</div>}
    </div>
  );
}

/** Single-series line with a crosshair tooltip. */
function LineChart({ values, format, height = 150, label }: { values: number[]; format: (v: number) => string; height?: number; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 560;
  const pad = { l: 36, r: 12, t: 10, b: 22 };
  if (values.length < 2) return <div className="muted" style={{ fontSize: 12.5 }}>Needs a few more turns to draw.</div>;
  const x = (i: number) => pad.l + (i / (values.length - 1)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v) * (height - pad.t - pad.b);
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label={label}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * width;
          setHover(Math.max(0, Math.min(values.length - 1, Math.round(((px - pad.l) / (width - pad.l - pad.r)) * (values.length - 1)))));
        }}>
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="rgba(255,255,255,.08)" strokeWidth={1} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="#8e8e96">{format(t)}</text>
          </g>
        ))}
        <path d={`${path} L${x(values.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={SERIES_1} opacity={0.1} />
        <path d={path} fill="none" stroke={SERIES_1} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r={4} fill={SERIES_1} stroke="#0e0e13" strokeWidth={2} />
        <text x={x(values.length - 1) - 6} y={y(values[values.length - 1]) - 9} textAnchor="end" fontSize="11" fill="#f5f5f7">
          {format(values[values.length - 1])}
        </text>
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} stroke="rgba(255,255,255,.35)" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(values[hover])} r={4} fill={SERIES_1} stroke="#0e0e13" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hover !== null && (
        <div className="viz-tip" style={{ left: `${(x(hover) / width) * 100}%` }}>Window {hover + 1}: <b>{format(values[hover])}</b></div>
      )}
    </div>
  );
}

/** Two-series stacked columns (own memory vs outside model) with legend + tooltip. */
function DailyColumns({ daily }: { daily: Core["daily"] }) {
  const [hover, setHover] = useState<string | null>(null);
  const days = Object.keys(daily).sort().slice(-14);
  if (days.length === 0) return <div className="muted" style={{ fontSize: 12.5 }}>No turns recorded yet.</div>;
  const max = Math.max(1, ...days.map((d) => daily[d].local + daily[d].api));
  const width = 560, height = 170, pad = { l: 30, r: 8, t: 10, b: 24 };
  const band = (width - pad.l - pad.r) / days.length;
  const bar = Math.min(24, band * 0.6);
  const yv = (v: number) => (v / max) * (height - pad.t - pad.b);
  const ticks = [0, Math.ceil(max / 2), max];
  return (
    <div style={{ position: "relative" }}>
      <div className="viz-legend">
        <span><i style={{ background: SERIES_1 }} />From its own memory</span>
        <span><i style={{ background: SERIES_2 }} />Asked an outside model</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Answers per day: from Nyx's own memory versus outside models">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={width - pad.r} y1={height - pad.b - yv(t)} y2={height - pad.b - yv(t)} stroke="rgba(255,255,255,.08)" />
            <text x={pad.l - 6} y={height - pad.b - yv(t) + 4} textAnchor="end" fontSize="10" fill="#8e8e96">{t}</text>
          </g>
        ))}
        {days.map((day, i) => {
          const { local, api: outside } = daily[day];
          const cx = pad.l + band * i + band / 2;
          const base = height - pad.b;
          const hLocal = yv(local), hApi = yv(outside);
          const gap = local && outside ? 2 : 0;
          return (
            <g key={day} onMouseEnter={() => setHover(day)} onMouseLeave={() => setHover(null)}>
              <rect x={cx - band / 2} y={pad.t} width={band} height={height - pad.t - pad.b} fill="transparent" />
              {local > 0 && <rect x={cx - bar / 2} y={base - hLocal} width={bar} height={hLocal} rx={outside ? 0 : 4} fill={SERIES_1} />}
              {outside > 0 && <path d={roundedTop(cx - bar / 2, base - hLocal - gap - hApi, bar, hApi)} fill={SERIES_2} />}
              {(i === days.length - 1 || days.length <= 7) && (
                <text x={cx} y={height - 8} textAnchor="middle" fontSize="10" fill="#8e8e96">{day.slice(5)}</text>
              )}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="viz-tip" style={{ left: `${((days.indexOf(hover) + 0.5) / days.length) * 100}%` }}>
          {hover}: <b>{daily[hover].local}</b> own · <b>{daily[hover].api}</b> outside
        </div>
      )}
      <TableToggle label="daily answers">
        <table className="viz-table">
          <thead><tr><th>Day</th><th>Own memory</th><th>Outside model</th></tr></thead>
          <tbody>{days.map((d) => <tr key={d}><td>{d}</td><td>{daily[d].local}</td><td>{daily[d].api}</td></tr>)}</tbody>
        </table>
      </TableToggle>
    </div>
  );
}

function roundedTop(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, h, w / 2);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

/** The real network, sampled: layers, strongest links, activations for the probe text. */
function NetworkCanvas({ view, reduced }: { view: Network | null; reduced: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!el || !view) return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const w = el.clientWidth, h = el.clientHeight;
    el.width = w * ratio; el.height = h * ratio;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    const heads = ["route", "domain", "tools"];
    const columns = [...view.layers.map((l) => l.name), "outputs"];
    const colX = (i: number) => 40 + (i / (columns.length - 1)) * (w - 120);
    const positions = new Map<string, { x: number; y: number; a: number }>();
    view.layers.forEach((layer, i) => {
      const ids = layer.neurons ?? layer.active ?? [];
      const acts = layer.activation ?? ids.map(() => 0.6);
      const maxA = Math.max(1e-6, ...acts);
      ids.forEach((id, j) => positions.set(`${layer.name}:${id}`, { x: colX(i), y: 24 + ((j + 0.5) / ids.length) * (h - 48), a: acts[j] / maxA }));
    });
    const outputs = heads.flatMap((head) => (view.heads[head]?.labels ?? []).map((label, j) => ({ head, label, v: view.heads[head].values[j] })));
    outputs.forEach((o, j) => positions.set(`out:${o.head}:${o.label}`, { x: colX(columns.length - 1), y: 18 + ((j + 0.5) / outputs.length) * (h - 36), a: o.v }));

    let frame = 0;
    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      for (const link of view.links) {
        const a = positions.get(`${link.from[0]}:${link.from[1]}`), b = positions.get(`${link.to[0]}:${link.to[1]}`);
        if (!a || !b) continue;
        const strength = Math.min(1, Math.abs(link.w) * 3);
        ctx.strokeStyle = link.w >= 0 ? `rgba(57,135,229,${0.08 + strength * 0.5})` : `rgba(217,89,38,${0.08 + strength * 0.5})`;
        ctx.lineWidth = 0.6 + strength;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      const last = view.layers[view.layers.length - 1];
      (last.neurons ?? []).forEach((id) => {
        const a = positions.get(`${last.name}:${id}`);
        if (!a) return;
        outputs.forEach((o) => {
          const b = positions.get(`out:${o.head}:${o.label}`)!;
          if (o.v < 0.15) return;
          ctx.strokeStyle = `rgba(245,245,247,${0.03 + o.v * 0.12})`;
          ctx.lineWidth = 0.5;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        });
      });
      const pulse = reduced ? 1 : 0.85 + 0.15 * Math.sin(t / 380);
      positions.forEach((p, key) => {
        const isOut = key.startsWith("out:");
        const r = isOut ? 3.5 : 2.5 + p.a * 3.5;
        ctx.fillStyle = `rgba(165,148,255,${(0.25 + p.a * 0.75) * (isOut ? 1 : pulse)})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
      });
      ctx.font = "10px ui-monospace, SF Mono, Consolas, monospace";
      ctx.fillStyle = "#8e8e96";
      columns.forEach((name, i) => {
        const layer = view.layers[i];
        ctx.textAlign = "center";
        ctx.fillText(layer ? `${name} · ${layer.size.toLocaleString()}` : "outputs", colX(i), 12);
      });
      ctx.textAlign = "left";
      outputs.forEach((o) => {
        const p = positions.get(`out:${o.head}:${o.label}`)!;
        if (o.v >= 0.2) { ctx.fillStyle = "#f5f5f7"; ctx.fillText(`${o.label} ${Math.round(o.v * 100)}%`, p.x + 8, p.y + 3); }
      });
      if (!reduced) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [view, reduced]);
  return <canvas ref={canvas} style={{ width: "100%", height: 320, display: "block" }} role="img"
    aria-label={view ? `Neural network with layers ${view.layers.map((l) => l.size).join(", ")}; strongest predictions shown on the right.` : "Neural network"} />;
}

export function LearnPanel() {
  const reduced = useReducedMotion();
  const [core, setCore] = useState<Core | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState("search the web for the latest GPU prices");
  const [network, setNetwork] = useState<Network | null>(null);
  const [recent, setRecent] = useState<Memory[]>([]);
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const [coreResult, recentResult] = await Promise.all([api.get<Core>("/api/core"), api.get<{ memories: Memory[] }>("/api/brain/recent?limit=24")]);
    if (coreResult.ok) { setCore(coreResult.data); setError(null); } else setError(coreResult.error);
    if (recentResult.ok) setRecent(recentResult.data.memories);
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 20000);
    return () => window.clearInterval(timer);
  }, [load]);
  useEffect(() => onWorkspaceEvent((e) => { if (e.type === "core.grew" || e.type === "brain.seeded") void load(); }), [load]);

  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(async () => {
      const result = await api.get<Network>(`/api/core/network?text=${encodeURIComponent(probe)}`);
      if (alive && result.ok) setNetwork(result.data);
    }, 250);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [probe, core?.examples]);

  const parts = useMemo(() => Object.entries(core?.parts ?? {}).sort((a, b) => b[1] - a[1]), [core]);
  const maxLog = Math.max(1, ...parts.map(([, v]) => Math.log10(v + 1)));

  const grow = async (body: Record<string, unknown>) => {
    const result = await api.post<{ running: boolean }>("/api/brain/seed", body);
    setMessage(result.ok ? "Growing in the background — watch the Nyx tab." : result.error);
  };

  if (error && !core) return <div className="page"><div className="page__inner"><ErrorState error={error} /></div></div>;
  if (!core) return <div className="page"><div className="page__inner"><Loading what="Measuring Nyx Core" /></div></div>;

  const domain = network?.heads.domain;
  const top = domain ? domain.labels.map((l, i) => [l, domain.values[i]] as const).sort((a, b) => b[1] - a[1])[0] : null;

  return (
    <div className="page">
      <div className="page__inner">
        <div className="page__head">
          <div>
            <div className="page__eyebrow">Nyx Core · its own model</div>
            <h1 className="page__title">Level {core.level} · {core.name}</h1>
            <p className="page__sub">
              {core.parameters.toLocaleString()} learned parameters — about as capable as {core.like}. It trains on every turn,
              grows its own network as it sees more, and leans on outside models only where it still needs to.
            </p>
          </div>
        </div>

        <div className="card learn-hero">
          <div className="learn-hero__figure">
            <div className="learn-hero__value">{compact(core.parameters)}</div>
            <div className="stat__label">learned parameters</div>
          </div>
          <div className="learn-hero__meter">
            <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(core.progress * 100)}
              aria-label={core.next_name ? `Progress to ${core.next_name}` : "Top level reached"}>
              <span style={{ width: `${Math.round(core.progress * 100)}%` }} />
            </div>
            <div className="stat__label" style={{ marginTop: 6 }}>
              {core.next_name ? `${Math.round(core.progress * 100)}% of the way to ${core.next_name} (${compact(core.next_at ?? 0)})` : "Top level reached"}
            </div>
          </div>
          <div className="grid-3" style={{ gridColumn: "1 / -1" }}>
            <div className="stat"><div className="stat__value">{Math.round(core.independence * 100)}%</div><div className="stat__label">answers from its own memory</div></div>
            <div className="stat"><div className="stat__value">{pct(core.domain_accuracy)}</div><div className="stat__label">topic accuracy (last 100, scored before training)</div></div>
            <div className="stat"><div className="stat__value">{core.examples.toLocaleString()}</div><div className="stat__label">turns learned from</div></div>
            <div className="stat"><div className="stat__value">{core.widths.join(" → ")}</div><div className="stat__label">neurons per hidden layer</div></div>
          </div>
        </div>

        <div className="card">
          <div className="section-title">The network, live <span className="hud-caption">{network?.parameters.toLocaleString()} weights</span></div>
          <label className="sr-only" htmlFor="probe">Type something to see how the network reads it</label>
          <input id="probe" className="text-input" value={probe} onChange={(e) => setProbe(e.target.value)}
            placeholder="Type anything — watch which neurons light up" />
          <div className="learn-net"><NetworkCanvas view={network} reduced={reduced} /></div>
          <div className="stat__label">
            {top ? <>It reads this as <b style={{ color: "var(--color-text)" }}>{top[0]}</b> ({Math.round(top[1] * 100)}%). </> : null}
            Blue links push toward an answer, orange away; brighter neurons are firing harder.
          </div>
          {core.growth_log.length > 0 && (
            <ul className="log-list" style={{ marginTop: 12, maxHeight: 160 }}>
              {core.growth_log.slice().reverse().map((g, i) => (
                <li key={i}><time>{new Date(g.ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time><span className="log-kind">grew</span><span>{g.event} after {g.examples} turns</span></li>
              ))}
            </ul>
          )}
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="section-title">Getting smarter <span className="hud-caption">topic accuracy</span></div>
            <LineChart values={core.accuracy_curve} format={(v) => `${Math.round(v * 100)}%`} label="Topic accuracy over time, scored before each turn trains the network" />
            <TableToggle label="accuracy">
              <table className="viz-table"><thead><tr><th>Window</th><th>Accuracy</th></tr></thead>
                <tbody>{core.accuracy_curve.map((v, i) => <tr key={i}><td>{i + 1}</td><td>{Math.round(v * 100)}%</td></tr>)}</tbody></table>
            </TableToggle>
          </div>
          <div className="card">
            <div className="section-title">Leaning on itself <span className="hud-caption">last 14 days</span></div>
            <DailyColumns daily={core.daily} />
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="section-title">Where the parameters are <span className="hud-caption">log scale</span></div>
            <div className="learn-parts">
              {parts.map(([key, value]) => (
                <div key={key} className="learn-part">
                  <span className="learn-part__label">{PART_LABELS[key] ?? key}</span>
                  <span className="learn-part__track"><span style={{ width: `${Math.max(1, (Math.log10(value + 1) / maxLog) * 100)}%` }} /></span>
                  <span className="learn-part__value">{value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="section-title">Crutches it still uses</div>
            {core.crutches.length === 0 ? (
              <div className="muted" style={{ fontSize: 12.5 }}>No outside-model answers recorded yet.</div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="viz-table">
                  <thead><tr><th>Topic</th><th>Model</th><th>Turns</th><th>Worked</th><th>Avg time</th></tr></thead>
                  <tbody>
                    {core.crutches.slice(0, 10).map((c) => (
                      <tr key={`${c.domain}${c.provider}${c.model}`}>
                        <td>{c.domain}</td><td>{c.provider} · {c.model}</td><td>{c.n}</td><td>{Math.round((c.ok / Math.max(1, c.n)) * 100)}%</td><td>{(c.avg_ms / 1000).toFixed(1)} s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="section-title">What it learned lately</div>
            <ul className="learn-feed">
              {recent.map((m) => (
                <li key={m.id}><span className="chip">{m.source}</span><span>{m.text.slice(0, 180)}</span></li>
              ))}
              {recent.length === 0 && <li className="muted">Nothing yet — talk to Nyx, or grow the brain below.</li>}
            </ul>
          </div>
          <div className="card">
            <div className="section-title">Grow the brain</div>
            <p className="stat__label" style={{ marginTop: 0, lineHeight: 1.5 }}>
              Nyx already learns from every turn and everything it reads. Point it at more to learn faster. Files are read
              on this PC and stay here; protected files (keys, passwords) are skipped.
            </p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
              <button className="btn btn-primary" onClick={() => void grow({})}>Learn from this PC's Nyx data</button>
            </div>
            <form style={{ display: "flex", gap: 8, marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); if (folder.trim()) void grow({ folder }); }}>
              <input className="text-input" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\Users\you\Documents" aria-label="Folder to study" />
              <button className="btn btn-secondary" type="submit" disabled={!folder.trim()}>Study folder</button>
            </form>
            {message && <p className="stat__label" aria-live="polite">{message}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
