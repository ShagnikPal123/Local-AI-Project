/** Windows the chat opens on things Ichos touches (redesign v3): a file, the mail inbox, a graph.
 * Read-only views over routes_workbench.py; the chat does the acting. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import "./workbench.css";

// --- File ---------------------------------------------------------------------------------------------------

interface Preview { kind: "text" | "image" | "binary"; name: string; path: string; size: number; mime: string; text?: string; data_url?: string; truncated?: boolean }

export function FileWindow({ path }: { path?: string }) {
  const [file, setFile] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [wanted, setWanted] = useState(path ?? "");
  const load = useCallback(async (p: string) => {
    if (!p.trim()) return;
    setError("");
    const r = await api.get<Preview>(`/api/files/preview?path=${encodeURIComponent(p.trim())}`);
    if (r.ok) setFile(r.data); else { setFile(null); setError(r.error); }
  }, []);
  useEffect(() => { if (path) void load(path); }, [path, load]);
  return (
    <div className="wb">
      <form className="wb__bar" onSubmit={(e) => { e.preventDefault(); void load(wanted); }}>
        <input value={wanted} onChange={(e) => setWanted(e.target.value)} placeholder="Paste a file path, or drag one in from the activity list" aria-label="File path" />
        <button className="btn btn-secondary" type="submit">Open</button>
      </form>
      {error && <p className="wb__error" role="alert">{error}</p>}
      {file && (
        <div className="wb__file">
          <div className="wb__meta"><b>{file.name}</b><span>{(file.size / 1024).toFixed(1)} KB{file.truncated ? " · first 400 KB" : ""}</span></div>
          {file.kind === "image" && <img src={file.data_url} alt={file.name} className="wb__image" />}
          {file.kind === "text" && <pre className="wb__text">{file.text}</pre>}
          {file.kind === "binary" && <p className="wb__muted">This file is not text or an image, so there is nothing to show here.</p>}
        </div>
      )}
      {!file && !error && <p className="wb__muted">Files Ichos reads or writes appear in the activity list — click or drag one here.</p>}
    </div>
  );
}

// --- Mail ---------------------------------------------------------------------------------------------------

interface Mail { id: string; from: string; subject: string; date: string; snippet: string; unread: boolean }

export function EmailWindow({ query: initial = "" }: { query?: string }) {
  const [query, setQuery] = useState(initial);
  const [items, setItems] = useState<Mail[] | null>(null);
  const [open, setOpen] = useState<{ subject?: string; from?: string; body?: string; text?: string } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (q: string) => {
    setError("");
    const r = await api.get<{ messages: Mail[] }>(`/api/email/list?limit=25&query=${encodeURIComponent(q)}`);
    if (r.ok) setItems(r.data.messages); else { setItems([]); setError(r.error); }
  }, []);
  useEffect(() => { void load(initial); }, [initial, load]);
  const read = async (id: string) => {
    const r = await api.get<{ subject?: string; from?: string; body?: string; text?: string }>(`/api/email/message/${encodeURIComponent(id)}`);
    if (r.ok) setOpen(r.data); else setError(r.error);
  };
  return (
    <div className="wb">
      <form className="wb__bar" onSubmit={(e) => { e.preventDefault(); void load(query); }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search mail" aria-label="Search mail" />
        <button className="btn btn-secondary" type="submit">Search</button>
      </form>
      {error && <p className="wb__error" role="alert">{error} — connect an account in Connections › Connectors.</p>}
      {open ? (
        <article className="wb__mail">
          <button className="btn btn-ghost" onClick={() => setOpen(null)}>← Inbox</button>
          <h3>{open.subject}</h3>
          <p className="wb__muted">{open.from}</p>
          <pre className="wb__text">{open.body ?? open.text}</pre>
        </article>
      ) : (
        <ul className="wb__list">
          {items === null && <li className="wb__muted">Reading the inbox…</li>}
          {items?.map((m) => (
            <li key={m.id}>
              <button className={`wb__row${m.unread ? " is-unread" : ""}`} onClick={() => void read(m.id)}
                draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", `Email "${m.subject}" from ${m.from}`)}>
                <b>{m.subject || "(no subject)"}</b>
                <span>{m.from} · {m.date.slice(0, 16)}</span>
                <small>{m.snippet}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Graph --------------------------------------------------------------------------------------------------

const CURVE_COLORS = ["#a594ff", "#5fd4f4", "#6fe3b4", "#ffc46b", "#f39bd6", "#ff8a8a"];

export function GraphWindow({ expressions: initial = ["sin(x)"], xMin = -10, xMax = 10 }: { expressions?: string[]; xMin?: number; xMax?: number }) {
  const [exprs, setExprs] = useState<string[]>(initial);
  const [draft, setDraft] = useState("");
  const [range, setRange] = useState<[number, number]>([xMin, xMax]);
  const [curves, setCurves] = useState<{ expression: string; ys: (number | null)[] }[]>([]);
  const [error, setError] = useState("");
  const [exact, setExact] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      const r = await api.post<{ curves: { expression: string; ys: (number | null)[] }[] }>("/api/math/sample", { expressions: exprs, x_min: range[0], x_max: range[1], points: 600 });
      if (r.ok) { setCurves(r.data.curves); setError(""); } else setError(r.error);
    }, 120);
    return () => window.clearTimeout(timer);
  }, [exprs, range]);

  const yRange = useMemo(() => {
    const all = curves.flatMap((c) => c.ys).filter((y): y is number => y !== null);
    if (!all.length) return [-1, 1] as [number, number];
    const sorted = [...all].sort((a, b) => a - b);
    const lo = sorted[Math.floor(sorted.length * 0.02)], hi = sorted[Math.floor(sorted.length * 0.98)];
    const pad = (hi - lo || 1) * 0.12;
    return [lo - pad, hi + pad] as [number, number];
  }, [curves]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = el.clientWidth, h = el.clientHeight;
    el.width = w * dpr; el.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const [x0, x1] = range, [y0, y1] = yRange;
    const px = (x: number) => ((x - x0) / (x1 - x0)) * w, py = (y: number) => h - ((y - y0) / (y1 - y0)) * h;
    ctx.strokeStyle = "rgba(255,255,255,0.06)"; ctx.lineWidth = 1;
    const step = (span: number) => Math.pow(10, Math.floor(Math.log10(span / 8)));
    const sx = step(x1 - x0), sy = step(y1 - y0);
    ctx.fillStyle = "rgba(195,198,214,0.7)"; ctx.font = "12px Segoe UI Variable Text, sans-serif";
    for (let x = Math.ceil(x0 / sx) * sx; x <= x1; x += sx) { ctx.beginPath(); ctx.moveTo(px(x), 0); ctx.lineTo(px(x), h); ctx.stroke(); }
    for (let y = Math.ceil(y0 / sy) * sy; y <= y1; y += sy) { ctx.beginPath(); ctx.moveTo(0, py(y)); ctx.lineTo(w, py(y)); ctx.stroke(); }
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    if (x0 < 0 && x1 > 0) { ctx.beginPath(); ctx.moveTo(px(0), 0); ctx.lineTo(px(0), h); ctx.stroke(); }
    if (y0 < 0 && y1 > 0) { ctx.beginPath(); ctx.moveTo(0, py(0)); ctx.lineTo(w, py(0)); ctx.stroke(); }
    ctx.fillText(x0.toPrecision(3), 4, h - 6); ctx.fillText(x1.toPrecision(3), w - 40, h - 6);
    ctx.fillText(y1.toPrecision(3), 4, 14); ctx.fillText(y0.toPrecision(3), 4, h - 22);
    curves.forEach((c, i) => {
      ctx.strokeStyle = CURVE_COLORS[i % CURVE_COLORS.length]; ctx.lineWidth = 2.2; ctx.beginPath();
      let pen = false;
      c.ys.forEach((y, k) => {
        if (y === null || y < y0 - (y1 - y0) * 3 || y > y1 + (y1 - y0) * 3) { pen = false; return; }
        const x = x0 + ((x1 - x0) * k) / (c.ys.length - 1);
        if (pen) ctx.lineTo(px(x), py(y)); else { ctx.moveTo(px(x), py(y)); pen = true; }
      });
      ctx.stroke();
    });
  }, [curves, range, yRange]);

  const zoom = (factor: number) => setRange(([a, b]) => { const mid = (a + b) / 2, half = ((b - a) / 2) * factor; return [mid - half, mid + half]; });
  const pan = (share: number) => setRange(([a, b]) => { const d = (b - a) * share; return [a + d, b + d]; });
  const runExact = async (op: string) => {
    const r = await api.post<{ result: string }>("/api/math/symbolic", { op, expression: exprs[0] ?? "" });
    setExact(r.ok ? `${op} of ${exprs[0]}: ${r.data.result}` : r.error);
  };

  return (
    <div className="wb wb--graph">
      <div className="wb__legend">
        {exprs.map((e, i) => (
          <span key={`${e}-${i}`} className="wb__chip" style={{ ["--c" as string]: CURVE_COLORS[i % CURVE_COLORS.length] }}>
            y = {e}<button aria-label={`Remove ${e}`} onClick={() => setExprs(exprs.filter((_, k) => k !== i))}>✕</button>
          </span>
        ))}
        <form onSubmit={(e) => { e.preventDefault(); if (draft.trim()) { setExprs([...exprs, draft.trim()].slice(-6)); setDraft(""); } }}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add y = …  (e.g. x^3 - 2x)" aria-label="Add a function" />
        </form>
      </div>
      <canvas ref={canvas} className="wb__canvas" role="img" aria-label={`Graph of ${exprs.join(", ")}`}
        onWheel={(e) => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.15 : 0.87); }} />
      <div className="wb__tools">
        <button className="btn btn-secondary" onClick={() => zoom(0.7)}>Zoom in</button>
        <button className="btn btn-secondary" onClick={() => zoom(1.4)}>Zoom out</button>
        <button className="btn btn-secondary" onClick={() => pan(-0.25)} aria-label="Pan left">←</button>
        <button className="btn btn-secondary" onClick={() => pan(0.25)} aria-label="Pan right">→</button>
        <span className="wb__sep" />
        {["derivative", "integral", "solve"].map((op) => <button key={op} className="btn btn-ghost" onClick={() => void runExact(op)}>{op}</button>)}
      </div>
      {error && <p className="wb__error" role="alert">{error}</p>}
      {exact && <p className="wb__exact">{exact}</p>}
    </div>
  );
}
