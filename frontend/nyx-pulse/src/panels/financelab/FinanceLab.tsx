/** The finance lab: the pot, the pipeline, the practice, the prediction.
 *
 * The owner sent a photo of a node graph with "each node lights up as it gets
 * used". The photo never arrived with the message, so the graph here is drawn
 * from the pipeline that actually runs — market data, forecast, strategies,
 * memory, decision, capital guard, trading rules, broker, log — and each node
 * really does light when that part does something.
 *
 * Everything else on the page is the owner's answer to "don't go broke": how
 * much money the AI may touch, how much is left, what it has learned from
 * losing, and the switch that hands the whole machine to finance.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import "./financelab.css";

type Pot = {
  allocated: number; earned: number; total: number; invested: number; cash: number; peak: number;
  drawdown_pct: number; loss_stop_pct: number; braking: boolean; stopped: boolean; mode: string;
  max_position: number; positions: Record<string, number>;
  lessons: { at: number; what: string; lesson: string }[];
};
type NodeRow = { id: string; label: string; what: string; group: string; count: number; hot: boolean; warm: boolean; detail: string };
type NodeMap = { nodes: NodeRow[]; edges: string[][]; hot_seconds: number };
type MemoryRow = { regime: string; strategy: string; runs: number; return_pct: number; beat_rate: number; worst_drawdown_pct: number };
type Overview = {
  pot: Pot;
  settings: { allocated: number; loss_stop_pct: number; max_position_pct: number; mode: string };
  nodes: NodeMap;
  memory: MemoryRow[];
  trained_at: number;
  strategies: { name: string; title: string; family: string }[];
  focus: { on: boolean; since: number; paused: { what: string }[]; offer: { high: boolean; why: string };
           warning: { stops: string[]; keeps: string[]; running_now: string[]; real_money: boolean } | null };
  models: { picked: { provider: string; model: string; local: boolean; why: string };
            rule: string; providers: { provider: string; verdict: string; why: string }[] };
};
type Forecast = {
  ok: boolean; last: number; days: { day: number; low: number; mid: number; high: number }[];
  expected_change_pct: number; band_pct: number[]; annual_volatility_pct: number; regime: string;
  confidence: number; note: string; headlines?: { title: string; url: string }[];
};

const money = (value: number) => `$${(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export function FinanceLab() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [symbol, setSymbol] = useState("");
  const [forecast, setForecast] = useState<{ symbol: string; forecast: Forecast; signals: { title: string; action: string; why: string }[] } | null>(null);
  const [advice, setAdvice] = useState<{ symbol: string; action: string; why: string; strategy: string } | null>(null);
  const [warn, setWarn] = useState(false);

  const load = useCallback(async () => {
    const got = await api.get<Overview>("/api/finance-lab");
    if (got.ok) { setData(got.data); setError(""); } else setError(got.error);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // The nodes are polled while the page is open, so they light in real time.
  useEffect(() => {
    const timer = window.setInterval(async () => {
      const got = await api.get<NodeMap>("/api/finance-lab/nodes");
      if (got.ok) setData((current) => (current ? { ...current, nodes: got.data } : current));
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  const saveMoney = useCallback(async (changes: Record<string, number | string>) => {
    setBusy("money");
    const got = await api.put<{ pot: Pot }>("/api/finance-lab/money", changes);
    if (got.ok) await load(); else setError(got.error);
    setBusy("");
  }, [load]);

  const runForecast = useCallback(async () => {
    const name = symbol.trim().toUpperCase();
    if (!name) return;
    setBusy("forecast");
    const got = await api.post<typeof forecast>("/api/finance-lab/forecast", { symbol: name, horizon: 20 }, 60_000);
    setBusy("");
    if (got.ok) { setForecast(got.data); setError(""); } else setError(got.error);
  }, [symbol]);

  const runAdvice = useCallback(async () => {
    const name = symbol.trim().toUpperCase();
    if (!name) return;
    setBusy("advise");
    const got = await api.post<typeof advice>("/api/finance-lab/advise", { symbol: name }, 60_000);
    setBusy("");
    if (got.ok) setAdvice(got.data); else setError(got.error);
  }, [symbol]);

  const train = useCallback(async () => {
    setBusy("train");
    const got = await api.post<{ ok: boolean; error?: string }>("/api/finance-lab/train",
      { symbols: symbol.trim() ? [symbol.trim().toUpperCase()] : [], background: true }, 30_000);
    setBusy("");
    if (!got.ok) setError(got.error);
    else if (!got.data.ok && got.data.error) setError(got.data.error);
    window.setTimeout(() => void load(), 4000);
  }, [symbol, load]);

  const focus = useCallback(async (action: "enter" | "leave") => {
    setBusy("focus");
    await api.post("/api/finance-lab/focus", { action }, 60_000);
    setBusy("");
    setWarn(false);
    void load();
  }, [load]);

  if (!data) return <div className="fl"><p className="fl-muted">{error || "Loading…"}</p></div>;
  const { pot, focus: focusState } = data;

  return (
    <div className="fl">
      {error && <p className="fl-error" role="alert">{error}</p>}

      <section className="fl-card fl-money">
        <div className="fl-money__head">
          <h2>Its money</h2>
          <span className={`fl-mode fl-mode--${pot.mode}`}>{pot.mode === "real" ? "REAL MONEY" : "Practice money"}</span>
        </div>
        <div className="fl-bar" role="img" aria-label={`${money(pot.invested)} invested of ${money(pot.total)}`}>
          <span className="fl-bar__invested" style={{ width: `${pot.total ? (pot.invested / pot.total) * 100 : 0}%` }} />
          <span className="fl-bar__cash" style={{ width: `${pot.total ? (pot.cash / pot.total) * 100 : 0}%` }} />
        </div>
        <div className="fl-figures">
          <Figure label="you allocated" value={money(pot.allocated)} />
          <Figure label="it earned" value={money(pot.earned)} tone={pot.earned >= 0 ? "ok" : "bad"} />
          <Figure label="free to use" value={money(pot.cash)} />
          <Figure label="in positions" value={money(pot.invested)} />
          <Figure label="down from peak" value={`${pot.drawdown_pct.toFixed(1)}%`} tone={pot.drawdown_pct > 0 ? "bad" : undefined} />
        </div>
        {pot.stopped && (
          <div className="fl-stop" role="alert">
            <b>Buying is stopped.</b> It is past its {pot.loss_stop_pct}% loss stop. What went wrong is below.
            <button className="fl-btn" disabled={busy === "money"} onClick={() => void api.post("/api/finance-lab/reset-stop", {}).then(load)}>
              Let it trade again
            </button>
          </div>
        )}
        {pot.braking && !pot.stopped && <p className="fl-note">It is down {pot.drawdown_pct.toFixed(1)}%, so every new buy is halved.</p>}
        <div className="fl-fields">
          <label>
            <span>Money it may use</span>
            <input type="number" min={0} step={50} defaultValue={pot.allocated}
                   onBlur={(e) => void saveMoney({ allocated: Number(e.target.value) })} />
          </label>
          <label>
            <span>Stop buying when down</span>
            <input type="number" min={1} max={90} defaultValue={pot.loss_stop_pct}
                   onBlur={(e) => void saveMoney({ loss_stop_pct: Number(e.target.value) })} />
            <i>%</i>
          </label>
          <label>
            <span>Most in one name</span>
            <input type="number" min={1} max={100} defaultValue={data.settings.max_position_pct}
                   onBlur={(e) => void saveMoney({ max_position_pct: Number(e.target.value) })} />
            <i>%</i>
          </label>
        </div>
        <p className="fl-fine">
          It can only ever use this pot and what it earns. There is no borrowing, no margin and no shorting anywhere
          in this code, so going into debt is not something it manages — it is something it cannot do.
        </p>
      </section>

      <section className="fl-card">
        <h2>The pipeline</h2>
        <p className="fl-muted">Each part lights as it runs.</p>
        <NodeGraph map={data.nodes} />
      </section>

      <section className="fl-card">
        <h2>Ask it about a symbol</h2>
        <div className="fl-ask">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="AAPL"
                 onKeyDown={(e) => { if (e.key === "Enter") void runForecast(); }} aria-label="Symbol" />
          <button className="fl-btn" disabled={busy === "forecast"} onClick={() => void runForecast()}>
            {busy === "forecast" ? "Working…" : "Forecast"}
          </button>
          <button className="fl-btn" disabled={busy === "advise"} onClick={() => void runAdvice()}>
            {busy === "advise" ? "Thinking…" : "What would you do?"}
          </button>
          <button className="fl-btn fl-btn--plain" disabled={busy === "train"} onClick={() => void train()}>
            {busy === "train" ? "Practising…" : "Practise on history"}
          </button>
        </div>
        {advice && (
          <div className="fl-advice">
            <b>{advice.symbol}: {advice.action}</b> <span className="fl-muted">({advice.strategy})</span>
            <p>{advice.why}</p>
          </div>
        )}
        {forecast?.forecast?.ok && <ForecastChart data={forecast.forecast} symbol={forecast.symbol} />}
        {forecast?.signals && forecast.signals.length > 0 && (
          <ul className="fl-signals">
            {forecast.signals.map((s) => (
              <li key={s.title}><b className={`fl-act fl-act--${s.action}`}>{s.action}</b> {s.title} — {s.why}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="fl-card">
        <div className="fl-money__head">
          <h2>What practice taught it</h2>
          <span className="fl-muted">{data.trained_at ? `trained ${new Date(data.trained_at * 1000).toLocaleDateString()}` : "not trained yet"}</span>
        </div>
        {data.memory.length === 0 ? (
          <p className="fl-muted">Nothing yet. "Practise on history" walks it through past markets first — that is the
            point of the simulator: it trains, then it does that.</p>
        ) : (
          <table className="fl-table">
            <thead><tr><th>Market</th><th>Strategy</th><th>Runs</th><th>Beat holding</th><th>Average</th><th>Worst fall</th></tr></thead>
            <tbody>
              {data.memory.map((row) => (
                <tr key={`${row.regime}-${row.strategy}`}>
                  <td>{row.regime}</td>
                  <td>{row.strategy}</td>
                  <td>{row.runs}</td>
                  <td>{Math.round(row.beat_rate * 100)}%</td>
                  <td className={row.return_pct >= 0 ? "is-ok" : "is-bad"}>{row.return_pct.toFixed(1)}%</td>
                  <td>{row.worst_drawdown_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {pot.lessons.length > 0 && (
        <section className="fl-card">
          <h2>What losing taught it</h2>
          <ul className="fl-lessons">
            {pot.lessons.map((lesson, index) => (
              <li key={`${lesson.at}-${index}`}>
                <b>{lesson.what}</b>
                <span>{lesson.lesson}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="fl-card">
        <h2>Who does the thinking</h2>
        <p className={`fl-picked${data.models.picked.local ? " is-local" : ""}`}>
          {data.models.picked.provider
            ? <>{data.models.picked.provider}{data.models.picked.model ? ` · ${data.models.picked.model}` : ""} — {data.models.picked.why}</>
            : data.models.picked.why}
        </p>
        <p className="fl-fine">{data.models.rule}</p>
        {data.models.providers.length > 0 && (
          <ul className="fl-providers">
            {data.models.providers.map((row) => (
              <li key={row.provider}><b>{row.provider}</b> <span className={`fl-verdict is-${row.verdict}`}>{row.verdict}</span> {row.why}</li>
            ))}
          </ul>
        )}
      </section>

      <section className={`fl-card fl-focus${focusState.on ? " is-on" : ""}`}>
        <h2>High finance</h2>
        {focusState.on ? (
          <>
            <p>Everything else is paused: {focusState.paused.map((p) => p.what).join(", ") || "nothing was running"}.</p>
            <button className="fl-btn" disabled={busy === "focus"} onClick={() => void focus("leave")}>
              Give the machine back
            </button>
          </>
        ) : (
          <>
            <p className="fl-muted">{focusState.offer.why}</p>
            {!warn && <button className="fl-btn" onClick={() => setWarn(true)}>Hand the machine to finance…</button>}
            {warn && focusState.warning && (
              <div className="fl-warning" role="alertdialog" aria-label="Turn everything else off?">
                <b>This stops everything else on this PC.</b>
                <p><u>Stops:</u> {focusState.warning.stops.join(", ")}</p>
                <p><u>Keeps:</u> {focusState.warning.keeps.join(", ")}</p>
                {focusState.warning.running_now.length > 0 &&
                  <p><u>Running right now:</u> {focusState.warning.running_now.join(", ")}</p>}
                {focusState.warning.real_money && <p className="fl-real">The lab is set to REAL money.</p>}
                <div className="fl-ask">
                  <button className="fl-btn fl-btn--danger" disabled={busy === "focus"} onClick={() => void focus("enter")}>
                    Yes, finance only
                  </button>
                  <button className="fl-btn fl-btn--plain" onClick={() => setWarn(false)}>Cancel</button>
                </div>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" }) {
  return (
    <div className="fl-figure">
      <b className={tone ? `is-${tone}` : ""}>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/** The pipeline, laid out in its three groups, with the used ones lit. */
function NodeGraph({ map }: { map: NodeMap }) {
  const groups: [string, string][] = [["in", "What it looks at"], ["think", "What it works out"], ["act", "What it does"]];
  return (
    <div className="fl-graph">
      {groups.map(([group, title]) => (
        <div key={group} className="fl-graph__col">
          <h3>{title}</h3>
          {map.nodes.filter((node) => node.group === group).map((node) => (
            <div key={node.id} className={`fl-node${node.hot ? " is-hot" : node.warm ? " is-warm" : ""}`}
                 title={`${node.what}${node.count ? ` · used ${node.count}×` : " · not used yet"}`}>
              <b>{node.label}</b>
              <span>{node.detail || node.what}</span>
              {node.count > 0 && <i className="fl-node__count">{node.count}</i>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** The cone: the middle path with the 10th–90th percentile band around it. */
function ForecastChart({ data, symbol }: { data: Forecast; symbol: string }) {
  const ref = useRef<SVGSVGElement>(null);
  const width = 640;
  const height = 200;
  const values = data.days.flatMap((d) => [d.low, d.high]).concat([data.last]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(data.days.length - 1, 1)) * (width - 40) + 30;
  const y = (value: number) => height - 24 - ((value - min) / span) * (height - 48);

  const band = data.days.map((d, i) => `${x(i)},${y(d.high)}`).join(" ") + " " +
    data.days.slice().reverse().map((d, i) => `${x(data.days.length - 1 - i)},${y(d.low)}`).join(" ");
  const mid = data.days.map((d, i) => `${x(i)},${y(d.mid)}`).join(" ");

  return (
    <figure className="fl-chart">
      <svg ref={ref} viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`${symbol}: middle path ${data.expected_change_pct}% with a band from ${data.band_pct[0]}% to ${data.band_pct[1]}%`}>
        <polygon points={band} className="fl-chart__band" />
        <polyline points={mid} className="fl-chart__mid" fill="none" />
        <line x1={30} x2={width - 10} y1={y(data.last)} y2={y(data.last)} className="fl-chart__now" />
        <text x={34} y={y(data.last) - 6} className="fl-chart__label">now {data.last.toFixed(2)}</text>
      </svg>
      <figcaption>
        <b>{symbol}</b> · {data.regime} market · {data.annual_volatility_pct}% volatility a year. {data.note}
        {data.headlines && data.headlines.length > 0 && (
          <span className="fl-heads">
            {data.headlines.slice(0, 3).map((h) => (
              <a key={h.url} className="nyx-link" href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a>
            ))}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
