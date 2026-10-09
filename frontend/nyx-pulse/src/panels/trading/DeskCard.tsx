/**
 * The trading desk (trading/desk.py, UPDATE_IDEAS U16): several AI traders, each with its own share of the money,
 * its own way of reading prices and its own market. The owner: "make multiple agents and split money between
 * them to trade in different ways in different markets and make more money."
 *
 * One switch turns the desk on (it then trades instead of the single picker); each trader is a row you can edit;
 * the shares always add up to 100 % and the desk itself moves money toward whoever is doing best.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";

interface Trader {
  id: string; name: string; strategy: string; market: string; share: number; enabled: boolean;
  pot: number; holdings: Record<string, number>; trades: number; value: number; cost: number; realized: number;
  gain: number; pct: number; strategy_title: string; market_title: string;
}
interface Shift { at: number; from: string; to: string; share: number; why: string }
interface Desk {
  enabled: boolean; agents: Trader[]; budget: number; shifts: Shift[]; runs: number;
  strategies: { id: string; title: string; family: string }[]; markets: { id: string; title: string }[];
  limits: { max_agents: number; min_share: number; max_share: number };
}

const money = (n: number) => n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function DeskCard({ isReal }: { isReal: boolean }) {
  const [desk, setDesk] = useState<Desk | null>(null);
  const [draft, setDraft] = useState<Trader[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const result = await api.get<Desk>("/api/trading/desk");
    if (result.ok) setDesk(result.data);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const save = async (body: Record<string, unknown>) => {
    setBusy(true);
    const result = await api.put<Desk>("/api/trading/desk", body);
    setBusy(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setDesk(result.data);
    setDraft(null);
  };

  if (!desk) return null;
  const rows = draft ?? desk.agents;
  const edit = (id: string, change: Partial<Trader>) => setDraft(rows.map((t) => (t.id === id ? { ...t, ...change } : t)));
  const totalShare = rows.filter((t) => t.enabled).reduce((sum, t) => sum + t.share, 0) || 1;

  return (
    <section className="t-card t-desk" aria-label="Trading desk">
      <div className="t-card__head">
        <h2>Trading desk</h2>
        <span className="t-tag">{isReal ? "real money" : "practice money"}</span>
        <button role="switch" aria-checked={desk.enabled} className="switch" aria-label="Trading desk on" disabled={busy}
                onClick={() => void save({ enabled: !desk.enabled })} />
      </div>
      <p className="t-muted">
        {desk.enabled
          ? `${rows.filter((t) => t.enabled).length} traders share the AI's ${money(desk.budget)} budget and trade instead of the single picker. Every order still goes through your rules and approvals.`
          : "Several AI traders, each with its own share of the AI's budget, its own strategy and its own market. Turn it on and they trade instead of the single picker."}
      </p>

      <div className="t-desk__rows" role="table" aria-label="Traders">
        <div className="t-desk__row t-desk__row--head" role="row">
          <span role="columnheader">Trader</span><span role="columnheader">Reads prices by</span>
          <span role="columnheader">Market</span><span role="columnheader">Share</span>
          <span role="columnheader">Result</span><span role="columnheader" aria-label="Remove" />
        </div>
        {rows.map((t) => (
          <div key={t.id} className={`t-desk__row${t.enabled ? "" : " is-off"}`} role="row">
            <span role="cell" className="t-desk__name">
              <input type="checkbox" checked={t.enabled} aria-label={`${t.name} trading`} onChange={(e) => edit(t.id, { enabled: e.currentTarget.checked })} />
              <input className="t-desk__input" value={t.name} aria-label="Trader name" onChange={(e) => edit(t.id, { name: e.currentTarget.value })} />
            </span>
            <span role="cell">
              <select value={t.strategy} aria-label={`${t.name}'s strategy`} onChange={(e) => edit(t.id, { strategy: e.currentTarget.value })}>
                {desk.strategies.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
              </select>
            </span>
            <span role="cell">
              <select value={t.market} aria-label={`${t.name}'s market`} onChange={(e) => edit(t.id, { market: e.currentTarget.value })}>
                {desk.markets.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
              </select>
            </span>
            <span role="cell" className="t-desk__share">
              <input type="range" min={0} max={100} value={Math.round((t.share / totalShare) * 100)} aria-label={`${t.name}'s share`}
                     disabled={!t.enabled} onChange={(e) => edit(t.id, { share: Number(e.currentTarget.value) / 100 })} />
              <b>{Math.round((t.share / totalShare) * 100)}%</b>
              <small className="t-muted">{money(t.pot)}</small>
            </span>
            <span role="cell" className={!t.trades ? "t-muted" : t.gain >= 0 ? "t-up" : "t-down"}>
              {t.trades ? `${t.gain >= 0 ? "+" : ""}${money(t.gain)} (${t.pct >= 0 ? "+" : ""}${t.pct}%)` : "no trades yet"}
              {Object.keys(t.holdings).length > 0 && <small className="t-muted"> · {Object.keys(t.holdings).join(", ")}</small>}
            </span>
            <span role="cell">
              <button className="t-link" disabled={rows.length <= 1} onClick={() => setDraft(rows.filter((r) => r.id !== t.id))}>Remove</button>
            </span>
          </div>
        ))}
      </div>

      <div className="t-desk__foot">
        <button className="t-link" disabled={rows.length >= desk.limits.max_agents}
                onClick={() => setDraft([...rows, { ...rows[0], id: "", name: `Trader ${rows.length + 1}`, share: 1 / (rows.length + 1),
                  enabled: true, holdings: {}, trades: 0, gain: 0, pct: 0, pot: 0, value: 0, cost: 0, realized: 0 }])}>
          + Add a trader
        </button>
        {draft && (
          <>
            <button className="btn btn-primary" disabled={busy} onClick={() => void save({ agents: draft })}>Save traders</button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => setDraft(null)}>Undo changes</button>
          </>
        )}
      </div>

      {desk.shifts.length > 0 && (
        <ul className="t-desk__shifts" aria-label="Money moved between traders">
          {desk.shifts.slice().reverse().slice(0, 4).map((s) => (
            <li key={s.at} className="t-muted">Moved {Math.round(s.share * 100)}% from {s.from} to {s.to} — {s.why}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
