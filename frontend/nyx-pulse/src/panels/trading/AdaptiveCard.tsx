/**
 * Adaptive mode — the one button. The owner: "a single button which turns it on … it goes hands
 * off and I can really only halt or stop the trader … it chooses all values, adds stocks and
 * researches stocks on its own."
 *
 * Off: one primary button, and optional fields that are blank by default (blank = the AI decides).
 * On: what it chose this scan and why, what the stock adder found, and what it learned — read-only,
 * with Stop here and Halt in the page header.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";

interface Schedule { enabled: boolean; days: number[]; start: string; end: string }
interface ScheduleState { active: boolean; inside: boolean; words: string }
interface AdaptiveStatus {
  on: boolean; pins: Record<string, number>; chosen: Record<string, number>; why: Record<string, string>;
  at: number | null; capital: number | null; schedule: Schedule; schedule_state: ScheduleState;
}
interface Added { at: number; why: string; ev: number; source: "news" | "universe"; thesis?: string }
interface DiscoveryRun { at: number; added: { symbol: string; why: string }[]; removed: { symbol: string; why: string }[]; considered: number; from_news: number }
interface Lesson { symbol: string; pl_pct: number; kind: string; at: number; lesson: string }
interface Extras {
  adaptive: AdaptiveStatus;
  discovery: { added: Record<string, Added>; last_run: number; last: DiscoveryRun | null };
  lessons: { summary: { exits: number; wins: number; win_rate: number | null; avg_pl_pct: number | null; losing_streak: number };
             recent: Lesson[]; cooldowns: Record<string, { until: number; losses: number; why: string }> };
  run: { summary: string; running: boolean; enabled: boolean; halted: boolean };
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function ago(stamp: number): string {
  const minutes = Math.round((Date.now() / 1000 - stamp) / 60);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

export function AdaptiveCard({ isReal, onChanged }: { isReal: boolean; onChanged: () => void }) {
  const [data, setData] = useState<Extras | null>(null);
  const [busy, setBusy] = useState(false);
  const [budget, setBudget] = useState("");
  const [startWith, setStartWith] = useState("");
  const [mode, setMode] = useState<"always" | "market">("always");
  const [schedule, setSchedule] = useState<Schedule>({ enabled: false, days: [0, 1, 2, 3, 4], start: "09:30", end: "16:00" });

  const load = useCallback(async () => {
    const result = await api.get<Extras>("/api/trading/adaptive");
    if (result.ok) setData(result.data);
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 20_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (data?.adaptive.schedule) setSchedule(data.adaptive.schedule);
  }, [data?.adaptive.schedule]);

  async function turn(on: boolean) {
    if (on && isReal && !window.confirm("This account uses REAL MONEY. Adaptive mode will choose its own budget and trade by itself "
      + "(orders above your “always ask above” amount still ask you first). Turn it on?")) return;
    if (on && Number(startWith) > 0 && !window.confirm(`Start the practice account again with ${money(Number(startWith))} first? Its positions and history are cleared.`)) return;
    setBusy(true);
    const result = await api.post<Extras>("/api/trading/adaptive", on ? {
      on: true,
      budget: Number(budget) > 0 ? Number(budget) : null,
      starting_cash: !isReal && Number(startWith) > 0 ? Number(startWith) : null,
      mode,
      schedule,
    } : { on: false }, 60_000);
    setBusy(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(on ? "Adaptive mode is on — hands-off. Halt or Stop whenever you like." : "Adaptive mode is off and the trader stopped.", "ok");
    setStartWith("");
    void load();
    onChanged();
  }

  async function discoverNow() {
    setBusy(true);
    const result = await api.post<{ result: DiscoveryRun }>("/api/trading/discover", {}, 180_000);
    setBusy(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    const added = result.data.result.added.map((a) => a.symbol).join(", ");
    pushToast(added ? `Added ${added} to the watchlist.` : `Looked at ${result.data.result.considered} stocks — nothing new worth adding right now.`, "ok");
    void load();
    onChanged();
  }

  if (!data) return null;
  const { adaptive, discovery, lessons } = data;
  const values = { ...adaptive.chosen, ...adaptive.pins };
  const pinned = (key: string) => key in adaptive.pins;
  const addedList = Object.entries(discovery.added).sort((a, b) => b[1].at - a[1].at).slice(0, 6);
  const cooling = Object.entries(lessons.cooldowns);

  const rows: { key: string; label: string; value: string }[] = [
    { key: "max_invested", label: "Budget", value: money(values.max_invested) },
    { key: "target_positions", label: "Spread across", value: values.target_positions ? `${Math.round(values.target_positions)} stocks` : "—" },
    { key: "max_per_trade", label: "Most in one stock", value: money(values.max_per_trade) },
    { key: "min_confidence", label: "Confidence needed", value: values.min_confidence ? `${Math.round(values.min_confidence * 100)}%` : "—" },
    { key: "stop_loss_pct", label: "Cuts a loser at", value: values.stop_loss_pct ? `−${values.stop_loss_pct}%` : "—" },
    { key: "take_profit_pct", label: "Takes profit at", value: values.take_profit_pct ? `+${values.take_profit_pct}%` : "—" },
    { key: "scan_minutes", label: "Scans every", value: values.scan_minutes ? `${Math.round(values.scan_minutes)} min` : "—" },
    { key: "max_trades_per_day", label: "Trades a day", value: (values.max_trades_per_day ?? 0) >= 10_000 ? "No limit" : String(Math.round(values.max_trades_per_day ?? 0)) },
  ];

  return (
    <section className={`t-card t-adaptive ${adaptive.on ? "is-on" : ""}`} aria-label="Adaptive mode">
      <div className="t-card__head">
        <h2>Adaptive mode</h2>
        <span className="t-tag">{adaptive.on ? "hands-off · on" : "hands-off"}</span>
      </div>

      {!adaptive.on ? (
        <>
          <p className="t-adaptive__pitch">
            One switch and it runs itself: it picks its own budget, spreads the money over several stocks, finds and
            researches new stocks, cuts losers and takes profits — re-deciding every scan. You can only Halt or Stop it.
          </p>
          <details className="t-adaptive__options">
            <summary>Optional — leave any of these blank and it decides</summary>
            <div className="t-adaptive__fields">
              <label className="t-field"><span>Budget it may invest</span>
                <input type="number" min="1" step="any" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="It decides" />
              </label>
              {!isReal && (
                <label className="t-field"><span>Start practice money at</span>
                  <input type="number" min="1" step="any" value={startWith} onChange={(e) => setStartWith(e.target.value)} placeholder="Keep current" />
                </label>
              )}
              <label className="t-field"><span>Runs</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as "always" | "market")}>
                  <option value="always">Until I stop it (24/7)</option>
                  <option value="market">US market hours only</option>
                </select>
              </label>
            </div>
            <fieldset className="t-adaptive__schedule">
              <legend>
                <label><input type="checkbox" checked={schedule.enabled} onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })} /> On only during my hours</label>
              </legend>
              {schedule.enabled && (
                <div className="t-adaptive__days">
                  {DAYS.map((day, index) => (
                    <label key={day} className={`t-chip ${schedule.days.includes(index) ? "is-on" : ""}`}>
                      <input type="checkbox" checked={schedule.days.includes(index)} onChange={(e) => setSchedule({
                        ...schedule, days: e.target.checked ? [...schedule.days, index].sort() : schedule.days.filter((d) => d !== index),
                      })} />{day}
                    </label>
                  ))}
                  <input type="time" aria-label="On from" value={schedule.start} onChange={(e) => setSchedule({ ...schedule, start: e.target.value })} />
                  <span className="t-muted">to</span>
                  <input type="time" aria-label="Off at" value={schedule.end} onChange={(e) => setSchedule({ ...schedule, end: e.target.value })} />
                  <span className="t-muted">your PC's time</span>
                </div>
              )}
            </fieldset>
          </details>
          <button className="btn btn-primary t-adaptive__go" disabled={busy} onClick={() => void turn(true)}>
            {busy ? "Turning On…" : "Turn On Adaptive Mode"}
          </button>
          {isReal && <p className="t-muted">Real money: orders above your “always ask above” amount still wait for you.</p>}
        </>
      ) : (
        <>
          <div className="t-when__state" role="status">
            <span className={`t-dot ${data.run.running ? "is-on" : ""}`} aria-hidden="true" />
            <span>{data.run.summary}</span>
            {adaptive.schedule_state?.active && <span className="t-muted"> · {adaptive.schedule_state.words}</span>}
          </div>

          <h3>What it chose {adaptive.at ? <span className="t-muted">· {ago(adaptive.at)}</span> : null}</h3>
          <dl className="t-adaptive__values">
            {rows.map((row) => (
              <div key={row.key} title={adaptive.why[row.key] ?? ""}>
                <dt>{row.label}{pinned(row.key) && <span className="t-tag">yours</span>}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
          {adaptive.why.max_invested && <p className="t-muted">{adaptive.why.max_invested} {adaptive.why.stop_loss_pct ?? ""}</p>}

          <h3>Stocks it added {discovery.last_run ? <span className="t-muted">· last looked {ago(discovery.last_run)}</span> : null}</h3>
          {addedList.length === 0 ? <p className="t-muted">None yet — it looks through its stock list and today's market news on every discovery pass.</p> : (
            <ul className="t-adaptive__list">
              {addedList.map(([symbol, info]) => (
                <li key={symbol}><b>{symbol}</b> <span className="t-tag">{info.source === "news" ? "from the news" : "from its list"}</span> <span className="t-muted">{info.why}</span></li>
              ))}
            </ul>
          )}

          <h3>What it learned</h3>
          <p className="t-muted">
            {lessons.summary.exits
              ? `${lessons.summary.exits} closed trades in 30 days, ${Math.round((lessons.summary.win_rate ?? 0) * 100)}% made money (average ${lessons.summary.avg_pl_pct ?? 0}%).`
              : "No closed trades yet."}
            {cooling.length > 0 && ` Cooling off: ${cooling.map(([s]) => s).join(", ")}.`}
          </p>
          {lessons.recent.length > 0 && (
            <ul className="t-adaptive__list">
              {lessons.recent.slice(0, 4).map((l) => <li key={`${l.symbol}${l.at}`}><span className={l.pl_pct >= 0 ? "t-delta is-up" : "t-delta is-down"}>{l.pl_pct >= 0 ? "▲" : "▼"}</span> {l.lesson}</li>)}
            </ul>
          )}

          <div className="t-adaptive__actions">
            <button className="btn btn-secondary" disabled={busy} onClick={() => void discoverNow()}>Find Stocks Now</button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => void turn(false)}>Stop Adaptive Mode</button>
          </div>
        </>
      )}
    </section>
  );
}
