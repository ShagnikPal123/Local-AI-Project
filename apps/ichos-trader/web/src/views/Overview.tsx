// Everything Shagnik listed on one screen: money and its predicted change, win rate, markets,
// increases, the bots' thinking, who is running, the next plan, predictions and research.
import { ago, money, pct, price, type Dashboard } from "../api";
import { Area, Cone, Donut, Spark } from "../charts";
import { Card, Pill, Tag } from "../ui";

export default function Overview({ d }: { d: Dashboard }) {
  const m = d.money;
  const curve = d.equity_curve.map((p) => p.equity);
  const risers = [...d.markets].filter((r) => (r.change_pct ?? 0) > 0).sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)).slice(0, 5);
  const rate = d.win_rate.rate;
  const working = d.bots.filter((b) => b.status === "working");
  return (
    <div className="grid overview">
      <Card title="Money" sub={d.money_kind === "practice" ? "practice account" : "real account"} accent className="stat">
        <div className="big">{money(m.equity, m.currency)}</div>
        <div className="row"><span className="muted">since start</span><Pill value={m.pl_pct} digits={2} /></div>
        <div className="row"><span className="muted">today {money(m.today_pl, m.currency)}</span><Pill value={m.today_pl_pct} digits={2} /></div>
      </Card>
      <Card title="Predicted" sub={`next ${m.predicted_horizon_h} h`} className="stat">
        <div className="big">{pct(m.predicted_pl_pct, 2)}</div>
        <Cone low={m.predicted_band_pct[0]} mid={m.predicted_pl_pct} high={m.predicted_band_pct[1]} span={Math.max(2, Math.abs(m.predicted_band_pct[0]), Math.abs(m.predicted_band_pct[1]))} />
        <div className="muted small">likely between {pct(m.predicted_band_pct[0])} and {pct(m.predicted_band_pct[1])}</div>
      </Card>
      <Card title="Win rate" sub={`${d.win_rate.closed} closed trades`} className="stat">
        <div className="donut-row">
          <Donut size={92} label={rate === null ? "–" : `${Math.round(rate * 100)}%`} parts={[
            { name: "wins", value: d.win_rate.wins, color: "var(--good)" },
            { name: "losses", value: Math.max(0, d.win_rate.closed - d.win_rate.wins), color: "var(--bad)" },
          ]} />
          <div className="muted small">{d.win_rate.wins} won<br />{d.win_rate.closed - d.win_rate.wins} lost<br />predictions right: {d.prediction_record.rate === null ? "–" : `${Math.round(d.prediction_record.rate * 100)}%`} of {d.prediction_record.graded}</div>
        </div>
      </Card>
      <Card title="Markets" sub="scanned last cycle" className="stat">
        <div className="big">{d.scanned}</div>
        <div className="muted small">{d.positions.length} held · {d.bots_running} of {d.bots.length} bots working</div>
        <div className="muted small">{d.speed.words}</div>
      </Card>

      <Card title="Equity" sub="practice account over time" className="wide-2">
        <Area values={curve} height={230} mark={curve.length > 1 ? money(Math.max(...curve), m.currency) + " best" : undefined}
          labels={d.equity_curve.length > 1 ? [new Date(d.equity_curve[0].t * 1000).toLocaleDateString(), "now"] : undefined} />
      </Card>

      <Card title="Thinking" sub="live, newest first" className="tall feed">
        <ul className="notes">
          {d.thinking.slice(0, 30).map((n, i) => (
            <li key={i} className={`note ${n.level}`}>
              <b>{n.bot}</b> <span className="muted">{n.role} · {ago(n.at)}</span>
              <p>{n.text}</p>
            </li>
          ))}
          {d.thinking.length === 0 && <li className="muted">Nothing yet. Press Start or Cycle.</li>}
        </ul>
      </Card>

      <Card title="Next plan" sub={d.plan.next_cycle_at ? `next cycle ${new Date(d.plan.next_cycle_at * 1000).toLocaleTimeString()}` : ""}>
        <ol className="steps">{(d.plan.steps ?? []).map((s) => <li key={s}>{s}</li>)}</ol>
        {d.plan.focus && d.plan.focus.length > 0 && <div className="chips">{d.plan.focus.map((f) => <Tag key={f}>{f}</Tag>)}</div>}
        <div className="muted small">{d.learning.words}</div>
      </Card>

      <Card title="Bots running" sub={`${working.length} working`}>
        <ul className="list">
          {d.bots.slice(0, 9).map((b) => (
            <li key={b.id}><span className={`dot ${b.status}`} /><b>{b.name}</b><span className="muted"> {b.role}</span><p className="muted small">{b.doing || "Waiting"}</p></li>
          ))}
        </ul>
      </Card>

      <Card title="Biggest increases" sub="today, from the scan">
        <ul className="list">
          {risers.map((r) => (
            <li key={r.symbol} className="line-row"><b>{r.symbol}</b><Spark values={r.sparkline} /><Pill value={r.change_pct} /></li>
          ))}
          {risers.length === 0 && <li className="muted">No risers in the last scan.</li>}
        </ul>
      </Card>

      <Card title="Holdings" sub={`${d.positions.length} open`} className="wide-2">
        <table>
          <thead><tr><th>Market</th><th>Bot</th><th>Value</th><th>Price</th><th>P/L</th></tr></thead>
          <tbody>
            {d.positions.map((p) => (
              <tr key={p.symbol}><td><b>{p.symbol}</b></td><td>{p.bot}</td><td>{money(p.value, m.currency)}</td><td>{price(p.price)}</td><td><Pill value={p.pl_pct} /></td></tr>
            ))}
            {d.positions.length === 0 && <tr><td colSpan={5} className="muted">Nothing held.</td></tr>}
          </tbody>
        </table>
      </Card>

      <Card title="Predictions" sub="next 24 h, graded after">
        <ul className="list">
          {d.predictions.slice(0, 6).map((p) => (
            <li key={p.symbol + p.made_at} className="pred">
              <b>{p.symbol}</b>
              <Cone low={p.low_pct} mid={p.expected_pct} high={p.high_pct} />
              <span className="small">{p.graded ? (p.right ? "✓ right" : "✗ wrong") : pct(p.expected_pct)}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Research" sub="from the numbers">
        <ul className="list">
          {d.research.slice(0, 4).map((r) => <li key={r.symbol + r.at}><b>{r.symbol}</b> <span className="muted small">{ago(r.at)}</span><p className="small">{r.summary}</p></li>)}
          {d.research.length === 0 && <li className="muted">No research yet.</li>}
        </ul>
      </Card>

      <Card title="Recent trades" sub="newest first" className="wide-2">
        <table>
          <thead><tr><th>When</th><th>Market</th><th>Side</th><th>Value</th><th>Bot</th><th>Why</th></tr></thead>
          <tbody>
            {d.trades.slice(0, 8).map((t, i) => (
              <tr key={i}><td className="muted">{ago(t.at)}</td><td><b>{t.symbol}</b></td><td><Tag tone={t.side === "buy" ? "good" : "warn"}>{t.side}</Tag></td>
                <td>{money(t.value, m.currency)}</td><td>{t.bot}</td><td className="why" title={t.reason}>{t.reason}</td></tr>
            ))}
            {d.trades.length === 0 && <tr><td colSpan={6} className="muted">No trades yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
