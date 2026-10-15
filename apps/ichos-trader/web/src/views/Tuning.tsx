// The tuning section: fully automatic by default, with dials and graphs for anyone who wants them.
// A dial the owner moves is pinned (auto leaves it alone) until "Back to auto" hands it back.
import { useEffect, useRef, useState } from "react";
import { api, money, type Dashboard, type SettingsView, type SpeedTest } from "../api";
import { Area, Bars, Dial } from "../charts";
import { Card, Tag } from "../ui";

const MARKET_NAMES: Record<string, string> = { crypto: "Crypto", stocks: "Stocks and ETFs", fx: "Currencies" };

type Slider = { key: string; label: string; help: string; step: number; show?: (v: number) => string; scale?: number };

const DIALS: Slider[] = [
  { key: "skeptic", label: "Skeptic strictness", help: "How easily the skeptic stops or shrinks a buy.", step: 0.05, show: (v) => (v < 0.34 ? "easy-going" : v < 0.67 ? "mild" : "strict") },
  { key: "max_positions", label: "Most holdings at once", help: "Across all traders.", step: 1 },
  { key: "max_position_pct", label: "Biggest single holding", help: "Share of the money in one market.", step: 0.01, scale: 100, show: (v) => `${Math.round(v * 100)}%` },
  { key: "stop_loss_pct", label: "Stop-loss", help: "Sell when a holding falls this far.", step: 0.5, show: (v) => `−${v}%` },
  { key: "take_profit_pct", label: "Take-profit", help: "Sell when a holding rises this far.", step: 0.5, show: (v) => `+${v}%` },
  { key: "pace_seconds", label: "Time between cycles", help: "Shorter reacts faster and uses more data.", step: 5, show: (v) => `${v} s` },
  { key: "scan_limit", label: "Markets to scan", help: "Up to this many each cycle.", step: 10 },
  { key: "max_bots", label: "Most bots", help: "The manager hires up to this many.", step: 1 },
];
const SHUTDOWN: Slider[] = [
  { key: "max_drawdown_pct", label: "Stop if the money falls", help: "From its best point.", step: 1, show: (v) => `${v}%` },
  { key: "slow_cycle_ms", label: "A cycle is slow after", help: "", step: 500, show: (v) => `${(v / 1000).toFixed(1)} s` },
  { key: "slow_cycles", label: "Slow cycles in a row", help: "Before it stops.", step: 1 },
  { key: "losing_hours", label: "Stop if still below start after", help: "", step: 1, show: (v) => `${v} h` },
  { key: "stale_data_s", label: "Pause when prices are older than", help: "", step: 30, show: (v) => `${Math.round(v / 60)} min` },
];

// One level deep, because settings like `shutdown` and `theme` are small objects saved by parts.
function merge(base: Record<string, unknown>, changes: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(changes)) {
    const old = out[k];
    out[k] = v && old && typeof v === "object" && typeof old === "object" && !Array.isArray(v) ? { ...(old as object), ...(v as object) } : v;
  }
  return out;
}

export default function Tuning({ d, owner, onChange }: { d: Dashboard; owner: boolean; onChange: () => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [speed, setSpeed] = useState<SpeedTest | null>(null);
  const [note, setNote] = useState("");
  const [cash, setCash] = useState("10000");
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<Record<string, unknown>>({});

  useEffect(() => { api.settings().then(setView).catch((e) => setNote(e.message)); }, []);

  // Moves are gathered for a moment and sent together, so dragging a dial is one save, not fifty.
  const save = (changes: Record<string, unknown>, now = false) => {
    pending.current = merge(pending.current, changes);
    setDraft(pending.current);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const send = pending.current;
      pending.current = {};
      try { setView(await api.saveSettings(send)); setDraft({}); setNote("Saved."); onChange(); } catch (e) { setNote((e as Error).message); }
    }, now ? 0 : 450);
  };
  if (!view) return <div className="splash small">{note || "Loading the dials…"}</div>;
  const s = merge(view.settings, draft) as SettingsView["settings"];
  const eff = view.effective;
  const lim = (k: string): [number, number] => view.limits[k] ?? [0, 1];
  const pinned = "risk" in (s.pins || {});

  const slider = (sl: Slider, value: number, set: (v: number) => void, limitKey: string) => (
    <label key={sl.key} className="slider">
      <span className="row"><b>{sl.label}</b><span>{sl.show ? sl.show(value) : value}</span></span>
      <input type="range" min={lim(limitKey)[0]} max={lim(limitKey)[1]} step={sl.step} value={value} disabled={!owner}
        onChange={(e) => set(Number(e.target.value))} />
      {sl.help && <small className="muted">{sl.help}</small>}
    </label>
  );

  return (
    <div className="grid tuning">
      <Card title="Mode" sub={s.auto ? "fully automatic" : "manual"} accent>
        <label className="toggle"><input type="checkbox" checked={s.auto} disabled={!owner} onChange={(e) => save({ auto: e.target.checked }, true)} /> Automatic: the manager tunes risk by itself</label>
        <label className="toggle"><input type="checkbox" checked={s.learn_first} disabled={!owner} onChange={(e) => save({ learn_first: e.target.checked }, true)} /> Learn first: study before the first buy</label>
        <div className="muted small">{d.learning.words}</div>
        <div className="chips">{Object.entries(s.markets).map(([k, on]) => (
          <label key={k} className="chip-toggle"><input type="checkbox" checked={on} disabled={!owner} onChange={(e) => save({ markets: { [k]: e.target.checked } }, true)} /> {MARKET_NAMES[k] ?? k}</label>))}
        </div>
      </Card>

      <Card title="Risk" sub={pinned ? "pinned by you" : s.auto ? "chosen by auto" : "manual"}>
        <div className="dial-row">
          <Dial value={Number(eff.risk)} auto={view.chosen.risk?.value} />
          <div>
            <div className="big">{Number(eff.risk).toFixed(2)}</div>
            <div className="muted small">{view.chosen.risk?.why ?? "Auto mode chooses after the manager's first review."}</div>
          </div>
        </div>
        <input type="range" min={0} max={1} step={0.05} value={Number(s.risk)} disabled={!owner} onChange={(e) => save({ risk: Number(e.target.value) })} />
        {pinned && owner && <button className="ghost" onClick={() => save({ unpin: ["risk"] }, true)}>Back to auto</button>}
      </Card>

      <Card title="Speed" sub="what fast means">
        <div className="row"><Tag tone={d.speed.grade === "fast" ? "good" : d.speed.grade === "slow" ? "bad" : "warn"}>{speed?.grade ?? d.speed.grade}</Tag>
          {owner && <button className="ghost" onClick={() => api.speedtest().then(setSpeed).catch((e) => setNote(e.message))}>Run speed test</button>}</div>
        <p className="small">{speed?.words ?? d.speed.words}</p>
        <Bars unit=" ms" items={Object.entries(speed?.stages ?? d.speed.stages).map(([label, value]) => ({ label, value }))} />
        <p className="muted small">Fast: a decision under 100 ms per market and a full cycle under 5 s.</p>
      </Card>

      <Card title="Dials" sub="pinned when you move them" className="wide-2">
        <div className="sliders">
          {DIALS.map((sl) => slider(sl, Number(s[sl.key]), (v) => save({ [sl.key]: v }), sl.key))}
        </div>
      </Card>

      <Card title="Auto shut-down" sub="when it is slow or losing">
        <div className="sliders one">
          {SHUTDOWN.map((sl) => slider(sl, Number(s.shutdown[sl.key]), (v) => save({ shutdown: { [sl.key]: v } }), `shutdown.${sl.key}`))}
        </div>
      </Card>

      <Card title="Equity" sub="practice account" className="wide-2">
        <Area values={d.equity_curve.map((p) => p.equity)} height={160} />
      </Card>

      <Card title="Look" sub="the trader's colours">
        <label className="row"><span>Accent</span><input type="color" value={s.theme.accent} disabled={!owner} onChange={(e) => save({ theme: { accent: e.target.value } })} /></label>
        <label className="row"><span>Mode</span>
          <select value={s.theme.mode} disabled={!owner} onChange={(e) => save({ theme: { mode: e.target.value } }, true)}>
            <option value="dark">Dark</option><option value="light">Light</option><option value="system">Follow the computer</option>
          </select></label>
        <hr />
        <label className="row"><span>Practice cash</span><input type="number" min={1} value={cash} disabled={!owner} onChange={(e) => setCash(e.target.value)} /></label>
        {owner && <button className="danger" onClick={() => {
          if (confirm(`Empty the practice account and start again with ${money(Number(cash))}?`)) api.resetPaper(Number(cash)).then(() => { setNote("Practice account reset."); onChange(); }).catch((e) => setNote(e.message));
        }}>Reset practice account</button>}
        {note && <p className="muted small">{note}</p>}
      </Card>
    </div>
  );
}
