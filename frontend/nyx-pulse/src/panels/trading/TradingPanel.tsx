/** Trading (Request G1): your account, Nyx's signals, and the rules the AI trades by.
 *
 * The thesis: the AI can watch the market and act for you, but only inside limits
 * you can read at a glance — and paper money is the default until you say otherwise.
 * Approvals sit at the top because they are the only thing that is waiting on you.
 *
 * Colour never carries meaning alone: gains and losses carry ▲/▼ and a sign, and
 * signals are words (Buy · Hold · Sell) with a confidence.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { Toasts } from "../../components/chat";
import { pushToast, useToasts, dismissToast } from "../../state/toastStore";
import { AdaptiveCard } from "./AdaptiveCard";
import { DeskCard } from "./DeskCard";
import "./trading.css";

interface BrokerInfo { name: string; label: string; kind: string; connected: boolean; live: boolean; fields: { name: string; label: string; secret?: boolean; type?: string }[]; signup_url: string; brokerages: string[] }
interface Session { phase: "regular" | "pre" | "after" | "closed"; open: boolean; reason: string; new_york: string; holiday: string; early_close: boolean; next_open: number; next_close: number }
interface RunState { mode: "market" | "always" | "until"; until: number | null; enabled: boolean; halted: boolean; running: boolean; summary: string; scan_minutes: number; last_scan_at: number; next_scan_at: number; resting: string; scans_this_run: number; session?: Session }
interface PaperSettings { realistic_fills: boolean; spread_bps: number; slippage_bps: number; commission: number; queue_when_closed: boolean; starting_cash: number }
interface PaperStats { start_equity: number; equity: number; pl: number; pl_pct: number; trades: number; closed: number; win_rate: number | null; realized: number; fees: number; max_drawdown_pct: number; history: { at: number; equity: number }[]; since: number; benchmark: { symbol?: string; change_pct?: number; would_be?: number } }
interface AiRules { enabled: boolean; approval: "always" | "above" | "never"; ask_above: number; max_per_trade: number; max_invested: number; max_trades_per_day: number; daily_loss_stop_pct: number; market_hours_only: boolean; allowed_symbols: string[]; scan_minutes: number; research_per_day: number; min_confidence: number }
interface Settings { active_broker: string; live_enabled: boolean; halted: boolean; ai: AiRules; watchlist: string[] }
interface Account { equity?: number; cash?: number; buying_power?: number; pl_total?: number; pl_day?: number | null; live?: boolean; error?: string }
interface Position { symbol: string; qty: number; avg_price: number; price: number; market_value: number; pl: number | null; pl_pct: number | null }
interface Order { id: string; symbol: string; side: string; qty?: number | null; notional?: number | null; type: string; status: string; filled_price?: number | null; requested_by?: string; created_at?: number | string }
interface Approval { id: string; order: { symbol: string; side: string; qty?: number | null; notional?: number | null; reason: string }; estimated_cost: number; price_at_request: number; live: boolean; expires_at: number; reasons: string[] }
interface Signal { symbol: string; signal?: "buy" | "hold" | "sell"; confidence?: number; reasons?: string[]; change_pct?: number | null; sparkline?: number[]; indicators?: { price: number; rsi14: number | null; return_20d: number }; error?: string }
interface State {
  brokers: BrokerInfo[]; settings: Settings; live_confirmation: string; account: Account; positions: Position[]; orders: Order[];
  approvals: Approval[]; ai_invested: number; autopilot: { running: boolean; today: { trades: number; research: number } };
  runs: { at: number; skipped: string | null; actions: { symbol: string; action: string; why?: string; result?: string }[] }[];
  track_record: { graded?: number; right?: number; hit_rate?: number | null; pending?: number; horizon_days?: number };
  audit: { at: number; kind: string; actor: string; reasons?: string[]; order?: { symbol: string; side: string } }[];
  disclaimer: string;
  money: "practice" | "real";
  money_label: string;
  session: Session;
  run: RunState;
  paper: { settings: PaperSettings; stats: PaperStats };
  effective_ai?: AiRules;
}

/** How long until a moment, in the words a person would use. */
function untilWords(stamp: number): string {
  const seconds = Math.max(0, stamp - Date.now() / 1000);
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "any moment";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

const usd = (n: number | null | undefined, digits = 2) =>
  n === null || n === undefined || Number.isNaN(n) ? "—" : n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: digits, minimumFractionDigits: digits });

function Delta({ value, suffix = "" }: { value: number | null | undefined; suffix?: string }) {
  if (value === null || value === undefined) return <span className="t-muted">—</span>;
  const up = value > 0, flat = value === 0;
  return (
    <span className={`t-delta ${flat ? "" : up ? "is-up" : "is-down"}`}>
      {flat ? "" : up ? "▲ " : "▼ "}{up ? "+" : ""}{suffix === "%" ? `${value.toFixed(2)}%` : usd(value)}
    </span>
  );
}

/** A single-series trend: de-emphasis line, current point in the accent, range in the tooltip. */
function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (!values || values.length < 2) return <span className="t-muted">—</span>;
  const w = 120, h = 32, pad = 3;
  const min = Math.min(...values), max = Math.max(...values);
  const x = (i: number) => pad + (i / (values.length - 1)) * (w - pad * 2);
  const y = (v: number) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const text = `${label}: ${usd(values[0])} → ${usd(values[values.length - 1])} over ${values.length} trading days (low ${usd(min)}, high ${usd(max)})`;
  return (
    <svg className="t-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={text}>
      <title>{text}</title>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2.5" className="t-spark__now" />
    </svg>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="t-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function TradingPanel() {
  const [state, setState] = useState<State | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  const [openReasons, setOpenReasons] = useState<string | null>(null);
  const [ticket, setTicket] = useState({ symbol: "", side: "buy", amountKind: "dollars", amount: "", type: "market", limit: "" });
  const [quote, setQuote] = useState<{ price: number; change_pct: number | null } | null>(null);
  const [placing, setPlacing] = useState(false);
  const [connectFor, setConnectFor] = useState<string | null>(null);
  const [connectValues, setConnectValues] = useState<Record<string, string>>({});
  const [liveTyped, setLiveTyped] = useState("");
  const [watchInput, setWatchInput] = useState("");
  const [scanning, setScanning] = useState(false);
  const [untilOpen, setUntilOpen] = useState(false);
  const [untilValue, setUntilValue] = useState("");
  const [resetCash, setResetCash] = useState("");
  const toasts = useToasts();

  const load = useCallback(async () => {
    const result = await api.get<State>("/api/trading/state");
    if (result.ok) setState(result.data);
    else pushToast(result.error, "warn");
  }, []);

  const loadSignals = useCallback(async () => {
    const result = await api.get<{ signals: Signal[]; market_open: boolean }>("/api/trading/signals");
    if (result.ok) { setSignals(result.data.signals); setMarketOpen(result.data.market_open); }
  }, []);

  useEffect(() => {
    void load();
    void loadSignals();
    const id = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(id);
  }, [load, loadSignals]);

  useEffect(() => {
    const symbol = ticket.symbol.trim().toUpperCase();
    if (!symbol) { setQuote(null); return; }
    const timer = window.setTimeout(async () => {
      const result = await api.get<{ price: number; change_pct: number | null }>(`/api/trading/quote?symbol=${encodeURIComponent(symbol)}`);
      setQuote(result.ok ? result.data : null);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [ticket.symbol]);

  async function saveSettings(changes: Record<string, unknown>, confirmation = "") {
    const result = await api.put<{ settings: Settings }>("/api/trading/settings", { changes, confirmation });
    if (!result.ok) { pushToast(result.error, "warn"); return false; }
    setState((s) => (s ? { ...s, settings: result.data.settings } : s));
    return true;
  }

  const setAi = (changes: Partial<AiRules>) => void saveSettings({ ai: changes });

  async function placeOrder() {
    const amount = Number(ticket.amount);
    if (!ticket.symbol.trim() || !(amount > 0)) return;
    const live = state?.money === "real";
    const words = `${ticket.side === "buy" ? "Buy" : "Sell"} ${ticket.amountKind === "dollars" ? usd(amount) + " of" : `${amount} shares of`} ${ticket.symbol.toUpperCase()}`;
    if (live && !window.confirm(`${words} with REAL money on ${state?.settings.active_broker}? This spends your own money.`)) return;
    setPlacing(true);
    const result = await api.post<{ status: string; reasons: string[] }>("/api/trading/orders", {
      symbol: ticket.symbol, side: ticket.side, type: ticket.type,
      ...(ticket.amountKind === "dollars" ? { notional: amount } : { qty: amount }),
      ...(ticket.type === "limit" ? { limit_price: Number(ticket.limit) } : {}),
    }, 60_000);
    setPlacing(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(result.data.status === "refused" ? result.data.reasons.join(" ") : `${words}: ${result.data.status.replace(/_/g, " ")}.`, result.data.status === "refused" ? "warn" : "ok");
    setTicket((t) => ({ ...t, amount: "" }));
    void load();
  }

  async function decide(approval: Approval, approve: boolean) {
    const result = await api.post<{ status: string }>(`/api/trading/approvals/${approval.id}`, { approve }, 60_000);
    if (!result.ok) pushToast(result.error, "warn");
    else pushToast(approve ? `Approved — ${result.data.status.replace(/_/g, " ")}.` : "Declined.", "ok");
    void load();
  }

  async function connect(broker: BrokerInfo) {
    const result = await api.post<{ account: Account }>(`/api/trading/brokers/${broker.name}/connect`, { values: connectValues }, 60_000);
    setConnectValues({});
    if (!result.ok) { pushToast(result.error, "warn"); void load(); return; }
    setConnectFor(null);
    pushToast(`${broker.name} connected.`, "ok");
    void load();
  }

  async function openPortal() {
    const result = await api.post<{ url: string }>("/api/trading/brokers/snaptrade/portal", {}, 60_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    window.open(result.data.url, "_blank", "noopener");
  }

  async function setRunMode(mode: RunState["mode"], until?: number) {
    const result = await api.post<{ run: RunState }>("/api/trading/run-mode", { mode, until: until ?? null }, 30_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(result.data.run.summary, "ok");
    void load();
  }

  async function stopTrader() {
    const result = await api.post<{ run: RunState }>("/api/trading/autopilot/stop", { reason: "You stopped it in the Trading tab" }, 30_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast("Stopped. Your positions are untouched.", "ok");
    void load();
  }

  async function savePaper(changes: Partial<PaperSettings>) {
    const result = await api.put<{ settings: PaperSettings }>("/api/trading/paper/settings", { changes });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    void load();
  }

  async function scanNow() {
    setScanning(true);
    const result = await api.post<{ actions: { symbol: string; action: string }[]; skipped: string | null }>("/api/trading/autopilot/scan", {}, 180_000);
    setScanning(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(result.data.skipped ?? `Scanned ${result.data.actions.length} symbols.`, "info");
    void load();
    void loadSignals();
  }

  const rules = state?.settings;
  const ai = rules?.ai;
  const isReal = state?.money === "real";
  const run = state?.run;
  const activeBroker = state?.brokers.find((b) => b.name === rules?.active_broker);
  const invested = state?.ai_invested ?? 0;
  // In adaptive mode the limits in force are the ones the AI chose this scan, not the saved ones.
  const live = state?.effective_ai?.max_invested ? state.effective_ai : ai;
  const budgetShare = live ? Math.min(1, invested / Math.max(1, live.max_invested)) : 0;
  const plTotal = state?.account.pl_total ?? state?.account.pl_day ?? null;
  const hitRate = state?.track_record.hit_rate;

  const approvalWords = useMemo(() => ({ always: "Ask me before every AI trade", above: "Ask only above an amount", never: "Trade within the budget without asking" }), []);

  if (!state || !rules || !ai) return <div className="trading trading--loading">Loading your trading account…</div>;

  return (
    <div className="trading">
      <header className="t-head">
        <div>
          <h1>Trading</h1>
          <p className="t-muted">{state.disclaimer}</p>
        </div>
        <div className="t-head__right">
          <select value={rules.active_broker} aria-label="Account" onChange={(e) => void saveSettings({ active_broker: e.target.value }).then(() => { void load(); })}>
            {state.brokers.filter((b) => b.connected).map((b) => <option key={b.name} value={b.name}>{b.label}</option>)}
          </select>
          <span className={`t-mode ${isReal ? "is-live" : ""}`}>{isReal ? "REAL MONEY" : "PRACTICE"}</span>
          {rules.halted ? (
            <button className="btn btn-secondary" onClick={() => void api.post("/api/trading/resume").then(load)}>Resume AI</button>
          ) : (
            <button className="btn t-halt" onClick={() => void api.post("/api/trading/halt", { reason: "Owner pressed Halt" }).then(() => { pushToast("Halted. The AI won't trade until you resume.", "ok"); void load(); })}>
              Halt AI
            </button>
          )}
        </div>
      </header>

      {/* Which money this is, said once, in the largest thing on the page. The owner:
          "just make it clear which one is real and fake". */}
      <div className={`t-money ${isReal ? "is-real" : "is-practice"}`} role="status">
        <b>{isReal ? "REAL MONEY" : "PRACTICE MONEY"}</b>
        <span>{state.money_label}</span>
        {!isReal && <span className="t-money__hint">Everything below is a simulation at real prices — nothing is bought or sold.</span>}
      </div>

      {state.approvals.length > 0 && (
        <section className="t-card t-approvals" aria-label="Waiting for your approval">
          <h2>Waiting for you</h2>
          {state.approvals.map((a) => (
            <div key={a.id} className="t-approval">
              <div>
                <b>{a.order.side === "buy" ? "Buy" : "Sell"} {a.order.notional ? `${usd(a.order.notional)} of` : `${a.order.qty} shares of`} {a.order.symbol}</b>
                <span className="t-muted"> · about {usd(a.estimated_cost)} at {usd(a.price_at_request)}{a.live ? " · REAL MONEY" : " · practice money"} · expires in {Math.max(0, Math.round((a.expires_at * 1000 - Date.now()) / 60000))} min</span>
                <p>{a.order.reason}</p>
              </div>
              <div className="t-approval__actions">
                <button className="btn btn-secondary" onClick={() => void decide(a, false)}>Decline</button>
                <button className="btn btn-primary" onClick={() => void decide(a, true)}>Approve</button>
              </div>
            </div>
          ))}
        </section>
      )}

      <AdaptiveCard isReal={isReal} onChanged={() => void load()} />
      <DeskCard isReal={isReal} />

      <section className="t-kpis" aria-label="Account">
        <div className="t-card t-kpi">
          <span className="t-kpi__label">Equity</span>
          <span className="t-kpi__value">{usd(state.account.equity)}</span>
          <Delta value={plTotal} />
          {state.account.error && <small className="t-error">{state.account.error}</small>}
        </div>
        <div className="t-card t-kpi">
          <span className="t-kpi__label">Cash</span>
          <span className="t-kpi__value">{usd(state.account.cash)}</span>
          <span className="t-muted">Buying power {usd(state.account.buying_power)}</span>
        </div>
        <div className="t-card t-kpi">
          <span className="t-kpi__label">AI budget in use</span>
          <span className="t-kpi__value">{usd(invested, 0)} <small>of {usd(live?.max_invested ?? 0, 0)}</small></span>
          <div className={`t-meter ${budgetShare > 0.9 ? "is-danger" : budgetShare > 0.7 ? "is-warn" : ""}`} role="meter" aria-valuemin={0} aria-valuemax={live?.max_invested ?? 0} aria-valuenow={invested} aria-label="AI budget in use">
            <div style={{ width: `${budgetShare * 100}%` }} />
          </div>
          <span className="t-muted">{(live?.max_trades_per_day ?? 0) >= 10_000 ? `${state.autopilot.today.trades} AI trades today · no limit` : `${state.autopilot.today.trades} of ${live?.max_trades_per_day} AI trades today`}</span>
        </div>
        <div className="t-card t-kpi">
          <span className="t-kpi__label">Signal hit rate</span>
          <span className="t-kpi__value">{hitRate === null || hitRate === undefined ? "—" : `${Math.round(hitRate * 100)}%`}</span>
          <span className="t-muted">{state.track_record.graded ? `${state.track_record.right} right of ${state.track_record.graded} graded after ${state.track_record.horizon_days} days` : `Grading starts ${state.track_record.horizon_days ?? 5} days after the first signal`}</span>
        </div>
      </section>

      <div className="t-grid">
        <section className="t-card" aria-label="Watchlist and signals">
          <div className="t-card__head">
            <h2>Watchlist</h2>
            <span className="t-muted">{marketOpen === null ? "" : marketOpen ? "US market open" : "US market closed"}</span>
            <button className="btn btn-secondary" onClick={() => void loadSignals()}>Refresh</button>
          </div>
          <div className="t-table-wrap">
            <table className="t-table">
              <thead><tr><th>Symbol</th><th className="num">Price</th><th className="num">Today</th><th>60 days</th><th>Signal</th><th aria-label="Remove" /></tr></thead>
              <tbody>
                {signals.map((s) => (
                  <Fragment key={s.symbol}>
                    <tr>
                      <td><button className="t-link" onClick={() => setTicket((t) => ({ ...t, symbol: s.symbol }))} title="Trade this">{s.symbol}</button></td>
                      <td className="num">{s.indicators ? usd(s.indicators.price) : "—"}</td>
                      <td className="num"><Delta value={s.change_pct ?? null} suffix="%" /></td>
                      <td className="t-spark-cell">{s.sparkline ? <Sparkline values={s.sparkline} label={s.symbol} /> : <span className="t-error">{s.error}</span>}</td>
                      <td>
                        {s.signal && (
                          <button className={`t-signal is-${s.signal}`} onClick={() => setOpenReasons(openReasons === s.symbol ? null : s.symbol)} aria-expanded={openReasons === s.symbol}>
                            {s.signal[0].toUpperCase() + s.signal.slice(1)}{s.signal !== "hold" ? ` · ${Math.round((s.confidence ?? 0) * 100)}%` : ""}
                          </button>
                        )}
                      </td>
                      <td><button className="t-x" aria-label={`Remove ${s.symbol}`} onClick={() => void saveSettings({ watchlist: rules.watchlist.filter((w) => w !== s.symbol) }).then(loadSignals)}>✕</button></td>
                    </tr>
                    {openReasons === s.symbol && (
                      <tr className="t-reasons"><td colSpan={6}>
                        <ul>{(s.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
                        <span className="t-muted">RSI {s.indicators?.rsi14 ?? "—"} · 20-day {s.indicators?.return_20d ?? "—"}% · a statistical signal, not advice</span>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <form className="t-inline" onSubmit={(e) => { e.preventDefault(); const sym = watchInput.trim().toUpperCase(); if (!sym) return; setWatchInput(""); void saveSettings({ watchlist: [...rules.watchlist, sym] }).then(loadSignals); }}>
            <input value={watchInput} onChange={(e) => setWatchInput(e.target.value)} placeholder="Add a symbol, e.g. AMD" aria-label="Add to watchlist" />
            <button className="btn btn-secondary" disabled={!watchInput.trim()}>Add</button>
          </form>
        </section>

        <section className="t-card" aria-label="Trade">
          <h2>Trade</h2>
          <div className="t-ticket">
            <div className="segmented" role="group" aria-label="Side">
              {(["buy", "sell"] as const).map((side) => <button key={side} aria-pressed={ticket.side === side} onClick={() => setTicket({ ...ticket, side })}>{side === "buy" ? "Buy" : "Sell"}</button>)}
            </div>
            <Field label="Symbol">
              <input value={ticket.symbol} onChange={(e) => setTicket({ ...ticket, symbol: e.target.value.toUpperCase() })} placeholder="AAPL" />
            </Field>
            {quote && <p className="t-quote">{usd(quote.price)} <Delta value={quote.change_pct} suffix="%" /></p>}
            <div className="segmented" role="group" aria-label="Amount in">
              <button aria-pressed={ticket.amountKind === "dollars"} onClick={() => setTicket({ ...ticket, amountKind: "dollars" })}>Dollars</button>
              <button aria-pressed={ticket.amountKind === "shares"} onClick={() => setTicket({ ...ticket, amountKind: "shares" })}>Shares</button>
            </div>
            <Field label={ticket.amountKind === "dollars" ? "Amount ($)" : "Shares"}>
              <input type="number" min="0" step="any" value={ticket.amount} onChange={(e) => setTicket({ ...ticket, amount: e.target.value })} />
            </Field>
            <div className="segmented" role="group" aria-label="Order type">
              <button aria-pressed={ticket.type === "market"} onClick={() => setTicket({ ...ticket, type: "market" })}>Market</button>
              <button aria-pressed={ticket.type === "limit"} onClick={() => setTicket({ ...ticket, type: "limit" })}>Limit</button>
            </div>
            {ticket.type === "limit" && <Field label="Limit price ($)"><input type="number" min="0" step="any" value={ticket.limit} onChange={(e) => setTicket({ ...ticket, limit: e.target.value })} /></Field>}
            <button className="btn btn-primary t-place" disabled={placing || !ticket.symbol || !(Number(ticket.amount) > 0)} onClick={() => void placeOrder()}>
              {placing ? "Placing…" : `${ticket.side === "buy" ? "Buy" : "Sell"} ${ticket.symbol || ""}${isReal ? " with REAL money" : " with practice money"}`}
            </button>
          </div>
        </section>
      </div>

      <div className="t-grid">
        <section className="t-card" aria-label="Positions">
          <h2>Positions</h2>
          {state.positions.length === 0 ? <p className="t-muted">No positions yet.</p> : (
            <div className="t-table-wrap">
              <table className="t-table">
                <thead><tr><th>Symbol</th><th className="num">Shares</th><th className="num">Avg</th><th className="num">Price</th><th className="num">Value</th><th className="num">P/L</th></tr></thead>
                <tbody>{state.positions.map((p) => (
                  <tr key={p.symbol}><td>{p.symbol}</td><td className="num">{p.qty.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td><td className="num">{usd(p.avg_price)}</td>
                    <td className="num">{usd(p.price)}</td><td className="num">{usd(p.market_value)}</td><td className="num"><Delta value={p.pl} /> <Delta value={p.pl_pct} suffix="%" /></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <h3>Recent orders</h3>
          {state.orders.length === 0 ? <p className="t-muted">No orders yet.</p> : (
            <ul className="t-orders">
              {state.orders.slice(0, 10).map((o) => (
                <li key={o.id}>
                  <b>{o.side === "buy" ? "Buy" : "Sell"} {o.symbol}</b> {o.notional ? usd(o.notional) : `${o.qty} sh`} · {o.status}{o.filled_price ? ` @ ${usd(o.filled_price)}` : ""}{o.requested_by === "ai" ? " · by AI" : ""}
                  {o.status === "open" && <button className="t-link" onClick={() => void api.del(`/api/trading/orders/${o.id}`).then(load)}>Cancel</button>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="t-card" aria-label="AI trader rules">
          <div className="t-card__head">
            <h2>AI trader</h2>
            <button role="switch" aria-checked={ai.enabled} className="switch" aria-label="AI trader on" disabled={rules.halted}
              onClick={() => setAi({ enabled: !ai.enabled })} />
          </div>
          <p className="t-muted">{ai.enabled ? `Scans your watchlist every ${ai.scan_minutes} minutes.` : "Off. Nyx only shows signals."} {rules.halted && "Halted."}</p>

          {/* When it works. "24/7 until I stop it" exists so nobody has to be at the
              keyboard at 9:30 — the schedule wakes itself at the opening bell. */}
          <div className="t-when">
            <div className="segmented t-when__modes" role="group" aria-label="When the AI trader works">
              <button aria-pressed={run?.mode === "market"} onClick={() => void setRunMode("market")}>Market hours</button>
              <button aria-pressed={run?.mode === "always"} onClick={() => void setRunMode("always")}>24/7 until I stop</button>
              <button aria-pressed={run?.mode === "until"} onClick={() => setUntilOpen(true)}>Until a time…</button>
            </div>
            <p className="t-when__state">
              <span className={`t-dot ${run?.running ? "is-on" : ""}`} aria-hidden="true" />
              <b>{run?.summary}</b>
              {run?.next_scan_at ? <span className="t-muted"> · next scan in {untilWords(run.next_scan_at)}</span> : null}
              {run?.resting ? <span className="t-muted"> · {run.resting}</span> : null}
            </p>
            <p className="t-muted">
              {state.session?.reason} New York time {state.session?.new_york?.slice(11) ?? ""}
              {state.session && !state.session.open ? ` · opens in ${untilWords(state.session.next_open)}` : ""}
            </p>
            {untilOpen && (
              <form className="t-inline" onSubmit={(e) => {
                e.preventDefault();
                const when = new Date(untilValue).getTime() / 1000;
                if (!when || Number.isNaN(when)) { pushToast("Pick a date and time first.", "warn"); return; }
                setUntilOpen(false);
                void setRunMode("until", when);
              }}>
                <input type="datetime-local" value={untilValue} onChange={(e) => setUntilValue(e.target.value)} aria-label="Work until" />
                <button className="btn btn-primary">Work Until Then</button>
                <button type="button" className="btn btn-secondary" onClick={() => setUntilOpen(false)}>Cancel</button>
              </form>
            )}
            {run?.enabled && <button className="btn btn-secondary" onClick={() => void stopTrader()}>Stop the AI Trader</button>}
          </div>
          <Field label="Approval">
            <select value={ai.approval} onChange={(e) => setAi({ approval: e.target.value as AiRules["approval"] })}>
              {(Object.keys(approvalWords) as AiRules["approval"][]).map((k) => <option key={k} value={k}>{approvalWords[k]}</option>)}
            </select>
          </Field>
          <div className="t-rules">
            <Field label="Max per trade ($)"><input type="number" defaultValue={ai.max_per_trade} onBlur={(e) => setAi({ max_per_trade: Number(e.target.value) })} /></Field>
            <Field label="Max the AI can invest ($)"><input type="number" defaultValue={ai.max_invested} onBlur={(e) => setAi({ max_invested: Number(e.target.value) })} /></Field>
            <Field label="Trades per day"><input type="number" defaultValue={ai.max_trades_per_day} onBlur={(e) => setAi({ max_trades_per_day: Number(e.target.value) })} /></Field>
            <Field label="Stop buying if down (%)"><input type="number" step="0.5" defaultValue={ai.daily_loss_stop_pct} onBlur={(e) => setAi({ daily_loss_stop_pct: Number(e.target.value) })} /></Field>
            {ai.approval === "above" && <Field label="Ask above ($)"><input type="number" defaultValue={ai.ask_above} onBlur={(e) => setAi({ ask_above: Number(e.target.value) })} /></Field>}
            <Field label="Scan every (min)"><input type="number" defaultValue={ai.scan_minutes} onBlur={(e) => setAi({ scan_minutes: Number(e.target.value) })} /></Field>
            <Field label="AI research per day" hint="News searches + model reads"><input type="number" defaultValue={ai.research_per_day} onBlur={(e) => setAi({ research_per_day: Number(e.target.value) })} /></Field>
            <Field label="Min signal confidence"><input type="number" step="0.05" min="0.5" max="0.99" defaultValue={ai.min_confidence} onBlur={(e) => setAi({ min_confidence: Number(e.target.value) })} /></Field>
          </div>
          <button className="btn btn-secondary" disabled={scanning} onClick={() => void scanNow()}>{scanning ? "Scanning…" : "Scan Now"}</button>
          {state.runs[0] && (
            <ul className="t-runs">
              {(state.runs[0].skipped ? [{ symbol: "", action: "skipped", why: state.runs[0].skipped }] : state.runs[0].actions).slice(0, 8).map((a, i) => (
                <li key={i}><b>{a.symbol || "Scan"}</b> {a.action}{a.result ? ` → ${a.result.replace(/_/g, " ")}` : ""}{a.why ? ` — ${a.why}` : ""}</li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {rules.active_broker === "paper" && (
        <section className="t-card t-practice" aria-label="Practice account">
          <div className="t-card__head">
            <h2>Practice account</h2>
            <span className="t-tag">simulated money · real prices</span>
          </div>
          <p className="t-muted">
            This is where you can be wrong for free. Orders cross the spread and slip a little, the commission you set is
            charged, and an order given while the market is shut waits for the opening bell — so what you learn here
            still holds when the money is real.
          </p>

          <div className="t-practice__stats">
            <div><span className="t-kpi__label">Value</span><b>{usd(state.paper.stats.equity)}</b>
              <Delta value={state.paper.stats.pl} /> <Delta value={state.paper.stats.pl_pct} suffix="%" /></div>
            <div><span className="t-kpi__label">Started with</span><b>{usd(state.paper.stats.start_equity)}</b>
              <span className="t-muted">{state.paper.stats.since ? new Date(state.paper.stats.since * 1000).toLocaleDateString() : ""}</span></div>
            <div><span className="t-kpi__label">Trades</span><b>{state.paper.stats.trades}</b>
              <span className="t-muted">{state.paper.stats.closed} closed{state.paper.stats.win_rate !== null ? ` · ${Math.round((state.paper.stats.win_rate ?? 0) * 100)}% went your way` : ""}</span></div>
            <div><span className="t-kpi__label">Costs paid</span><b>{usd(state.paper.stats.fees)}</b>
              <span className="t-muted">worst dip {state.paper.stats.max_drawdown_pct}%</span></div>
            <div><span className="t-kpi__label">Just holding SPY</span>
              <b>{state.paper.stats.benchmark?.change_pct === undefined ? "—" : `${state.paper.stats.benchmark.change_pct > 0 ? "+" : ""}${state.paper.stats.benchmark.change_pct}%`}</b>
              <span className="t-muted">{state.paper.stats.benchmark?.would_be ? `would be ${usd(state.paper.stats.benchmark.would_be)}` : "the lazy comparison"}</span></div>
          </div>
          {state.paper.stats.history?.length > 1 && (
            <div className="t-practice__curve">
              <Sparkline values={state.paper.stats.history.map((p) => p.equity)} label="Practice account" />
              <span className="t-muted">{state.paper.stats.history.length} readings since you started</span>
            </div>
          )}

          <h3>Start again with</h3>
          <div className="t-practice__cash">
            {[50, 1000, 10000, 100000].map((amount) => (
              <button key={amount} className="btn btn-secondary" onClick={() => {
                if (!window.confirm(`Start the practice account again with ${usd(amount, 0)} of pretend money? Its positions and history are cleared.`)) return;
                void api.post("/api/trading/paper/reset", { cash: amount }).then(load);
              }}>{usd(amount, 0)}</button>
            ))}
            <form className="t-inline" onSubmit={(e) => {
              e.preventDefault();
              const amount = Number(resetCash);
              if (!(amount > 0)) return;
              if (!window.confirm(`Start the practice account again with ${usd(amount, 0)}?`)) return;
              setResetCash("");
              void api.post("/api/trading/paper/reset", { cash: amount }).then(load);
            }}>
              <input type="number" min="1" step="any" value={resetCash} onChange={(e) => setResetCash(e.target.value)} placeholder="Any amount" aria-label="Custom starting amount" />
              <button className="btn btn-secondary" disabled={!(Number(resetCash) > 0)}>Use This</button>
            </form>
          </div>

          <details className="t-practice__realism">
            <summary>How real it feels</summary>
            <label className="t-check">
              <input type="checkbox" checked={state.paper.settings.realistic_fills} onChange={(e) => void savePaper({ realistic_fills: e.target.checked })} />
              Realistic fills — pay the spread and a little slippage
            </label>
            <label className="t-check">
              <input type="checkbox" checked={state.paper.settings.queue_when_closed} onChange={(e) => void savePaper({ queue_when_closed: e.target.checked })} />
              Orders given while the market is shut wait for the opening bell
            </label>
            <div className="t-rules">
              <Field label="Spread (bps)" hint="4 = 0.04%"><input type="number" step="0.5" defaultValue={state.paper.settings.spread_bps} onBlur={(e) => void savePaper({ spread_bps: Number(e.target.value) })} /></Field>
              <Field label="Slippage (bps)"><input type="number" step="0.5" defaultValue={state.paper.settings.slippage_bps} onBlur={(e) => void savePaper({ slippage_bps: Number(e.target.value) })} /></Field>
              <Field label="Commission ($/order)"><input type="number" step="0.01" defaultValue={state.paper.settings.commission} onBlur={(e) => void savePaper({ commission: Number(e.target.value) })} /></Field>
            </div>
          </details>
        </section>
      )}

      <section className="t-card" aria-label="Brokers">
        <h2>Accounts</h2>
        <p className="t-muted">
          The practice account works now and uses no money at all. Alpaca connects directly. SnapTrade connects the account you already have at {state.brokers.find((b) => b.name === "snaptrade")?.brokerages.slice(0, 8).join(", ")} and more — you sign in on your broker's own page.
          Apps with no trading API can't be traded from Nyx.
        </p>
        <div className="t-brokers">
          {state.brokers.map((b) => (
            <div key={b.name} className={`t-broker${b.connected ? " is-connected" : ""}`}>
              <div className="t-broker__head">
                <b>{b.label}</b>
                <span className="t-muted">{b.name === "paper" ? "Ready" : b.connected ? (b.live ? "Connected · live" : "Connected") : "Not connected"}</span>
              </div>
              {b.name !== "paper" && (
                <div className="t-broker__actions">
                  {b.signup_url && !b.connected && <a className="btn btn-secondary" href={b.signup_url} target="_blank" rel="noreferrer">Get Keys ↗</a>}
                  {!b.connected && <button className="btn btn-secondary" onClick={() => { setConnectFor(connectFor === b.name ? null : b.name); setConnectValues({}); }}>{connectFor === b.name ? "Cancel" : "Connect"}</button>}
                  {b.connected && b.name === "snaptrade" && <button className="btn btn-primary" onClick={() => void openPortal()}>Connect a Brokerage</button>}
                  {b.connected && <button className="btn btn-secondary" onClick={() => void api.del(`/api/trading/brokers/${b.name}`).then(load)}>Disconnect</button>}
                </div>
              )}
              {b.name === "paper" && <span className="t-muted">Starting amount and realism are in “Practice account” above.</span>}
              {connectFor === b.name && (
                <form className="t-connect" onSubmit={(e) => { e.preventDefault(); void connect(b); }}>
                  {b.fields.map((f) => f.type === "boolean" ? (
                    <label key={f.name} className="t-check"><input type="checkbox" checked={connectValues[f.name] === "true"} onChange={(e) => setConnectValues({ ...connectValues, [f.name]: String(e.target.checked) })} /> {f.label}</label>
                  ) : (
                    <Field key={f.name} label={f.label}><input type={f.secret ? "password" : "text"} autoComplete="off" value={connectValues[f.name] ?? ""} onChange={(e) => setConnectValues({ ...connectValues, [f.name]: e.target.value })} /></Field>
                  ))}
                  <button className="btn btn-primary">Save and Test</button>
                </form>
              )}
            </div>
          ))}
        </div>

        <div className="t-live">
          <b>Live money</b>
          {rules.live_enabled ? (
            <>
              <span className="t-muted">On — orders on live accounts use real money.</span>
              <button className="btn btn-secondary" onClick={() => void saveSettings({ live_enabled: false })}>Turn Off</button>
            </>
          ) : (
            <form className="t-inline" onSubmit={(e) => { e.preventDefault(); void saveSettings({ live_enabled: true }, liveTyped).then((ok) => { if (ok) { setLiveTyped(""); pushToast("Live trading is on.", "warn"); } }); }}>
              <span className="t-muted">Off. To allow real-money orders on a live account, type “{state.live_confirmation}”.</span>
              <input value={liveTyped} onChange={(e) => setLiveTyped(e.target.value)} aria-label="Type the confirmation to turn on live trading" />
              <button className="btn btn-secondary" disabled={liveTyped.trim() !== state.live_confirmation}>Turn On</button>
            </form>
          )}
          {activeBroker && !activeBroker.live && <span className="t-muted">The active account is paper, so this switch doesn't affect it.</span>}
        </div>
      </section>

      <details className="t-card t-audit">
        <summary>Activity log ({state.audit.length})</summary>
        <ul>
          {state.audit.map((a, i) => (
            <li key={i}><span className="t-muted">{new Date(a.at * 1000).toLocaleString()}</span> · <b>{a.kind.replace(/_/g, " ")}</b> by {a.actor}{a.order ? ` · ${a.order.side} ${a.order.symbol}` : ""}{a.reasons ? ` — ${a.reasons.join(" ")}` : ""}</li>
          ))}
        </ul>
      </details>
      <Toasts items={toasts} onDismiss={dismissToast} />
    </div>
  );
}
