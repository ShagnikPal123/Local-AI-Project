/** Studio Glass: the greeting and the four stat cards above the chat (owner, 2026-10-10 — glassy dashboard reference).
 *
 * The reference's Calories / Heart rate / Steps / Sleep become Ichos's own vitals, all live from /api/brain/summary:
 * what it remembers, how fast its brain is firing, what it learned today, and its thinking queue. Each card has the
 * small chart the reference uses (bars, a pulse line, a half gauge, bars). Collapsible, remembered.
 */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Summary {
  memories: number;
  memories_24h: number;
  impulses_per_min?: number;
  queue?: number;
  clusters?: { id: string; label?: string; count: number }[];
}

function greeting(now: Date): string {
  const h = now.getHours();
  if (h < 5) return "Up late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const fmt = (n: number) => n.toLocaleString();

function Bars({ values, tone }: { values: number[]; tone: string }) {
  const max = Math.max(1, ...values);
  return (
    <svg className="studio-stat__chart" viewBox="0 0 64 28" aria-hidden="true">
      {values.map((v, i) => {
        const h = 4 + (v / max) * 22;
        return <rect key={i} x={i * (64 / values.length) + 1} y={28 - h} width={Math.max(2, 64 / values.length - 3)} height={h} rx="1.5" fill={tone} opacity={0.35 + 0.65 * (v / max)} />;
      })}
    </svg>
  );
}

function Pulse({ tone, rate }: { tone: string; rate: number }) {
  const amp = Math.min(12, 4 + rate / 4);
  const d = `M0 16 H18 L22 ${16 - amp} L26 ${16 + amp * 0.7} L30 16 H40 L43 ${16 - amp * 0.6} L46 16 H64`;
  return (
    <svg className="studio-stat__chart" viewBox="0 0 64 28" aria-hidden="true">
      <path d={d} fill="none" stroke={tone} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Gauge({ tone, share }: { tone: string; share: number }) {
  const r = 22, len = Math.PI * r, s = Math.max(0.04, Math.min(1, share));
  return (
    <svg className="studio-stat__chart" viewBox="0 0 64 32" aria-hidden="true">
      <path d="M10 30 A22 22 0 0 1 54 30" fill="none" stroke="currentColor" strokeOpacity="0.14" strokeWidth="5" strokeLinecap="round" />
      <path d="M10 30 A22 22 0 0 1 54 30" fill="none" stroke={tone} strokeWidth="5" strokeLinecap="round" strokeDasharray={`${len * s} ${len}`} />
    </svg>
  );
}

export function StudioHeader({ name, onSearch, onBell }: { name: string; onSearch: () => void; onBell: () => void }) {
  const [s, setS] = useState<Summary | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("ichos.studio.stats") !== "0"; } catch { return true; } });
  useEffect(() => { try { localStorage.setItem("ichos.studio.stats", open ? "1" : "0"); } catch { /* not kept */ } }, [open]);
  useEffect(() => {
    let alive = true;
    const load = () => void api.get<Summary>("/api/brain/summary").then((r) => { if (alive && r.ok) setS(r.data); });
    load();
    const id = window.setInterval(() => { load(); setNow(new Date()); }, 30_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  const clusters = (s?.clusters ?? []).map((c) => c.count).slice(0, 9);
  const rate = s?.impulses_per_min ?? 0;
  const today = s?.memories_24h ?? 0;
  const queue = s?.queue ?? 0;

  return (
    <section className="studio-head" aria-label="Today">
      <div className="studio-head__top">
        <div>
          <h1 className="studio-head__hello">{greeting(now)}, <b>{name}</b> <span aria-hidden="true">👋</span></h1>
          <p className="studio-head__sub">
            {now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })} · let's make something today
          </p>
        </div>
        <div className="studio-head__tools">
          <button type="button" className="studio-search" onClick={onSearch} title="Find a tab, or make one (Ctrl+K)">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M21 21l-5-5" /></svg>
            <span>Search anything…</span><kbd>Ctrl K</kbd>
          </button>
          <button type="button" className="studio-bell" onClick={onBell} title="Status and what needs you" aria-label="Status">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
            {queue > 0 && <span className="studio-bell__dot" />}
          </button>
          <button type="button" className="studio-fold" onClick={() => setOpen((v) => !v)} aria-expanded={open} title={open ? "Hide the vitals" : "Show the vitals"}>
            <svg width="14" height="14" viewBox="0 0 12 12" aria-hidden="true"><path d={open ? "M3 7.5 6 4.5 9 7.5" : "M3 4.5 6 7.5 9 4.5"} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
          </button>
        </div>
      </div>
      {open && (
        <div className="studio-stats">
          <article className="studio-stat" style={{ ["--k" as string]: "var(--studio-orange)" }}>
            <header><span>Memories</span><i aria-hidden="true">◉</i></header>
            <Bars values={clusters.length ? clusters : [3, 5, 4, 7, 6, 8, 5]} tone="var(--studio-orange)" />
            <strong>{s ? fmt(s.memories) : "—"}</strong><small>kept</small>
          </article>
          <article className="studio-stat" style={{ ["--k" as string]: "var(--studio-rose)" }}>
            <header><span>Brain pulse</span><i aria-hidden="true">♥</i></header>
            <Pulse tone="var(--studio-rose)" rate={rate} />
            <strong>{s ? fmt(rate) : "—"}</strong><small>impulses/min</small>
          </article>
          <article className="studio-stat" style={{ ["--k" as string]: "var(--studio-green)" }}>
            <header><span>Learned today</span><i aria-hidden="true">✦</i></header>
            <Gauge tone="var(--studio-green)" share={s && s.memories ? today / Math.max(today * 4, 40) : 0.1} />
            <strong>{s ? fmt(today) : "—"}</strong><small>new</small>
          </article>
          <article className="studio-stat" style={{ ["--k" as string]: "var(--studio-blue)" }}>
            <header><span>Thinking queue</span><i aria-hidden="true">☾</i></header>
            <Bars values={[2, 4, 3, 6, 5, 7, 4, 6, 5].map((v) => v + queue)} tone="var(--studio-blue)" />
            <strong>{s ? fmt(queue) : "—"}</strong><small>waiting</small>
          </article>
        </div>
      )}
    </section>
  );
}
