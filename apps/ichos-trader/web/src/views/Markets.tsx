// The ranked scan: why each market sits where it does (liquidity, spread, depth, order flow).
import { useState } from "react";
import { price, type Dashboard } from "../api";
import { Spark } from "../charts";
import { Card, Pill, Tag } from "../ui";

const KINDS = ["all", "crypto", "stock", "etf", "fx"];

function Meter({ value }: { value: number }) {
  return <span className="meter"><i style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} /></span>;
}

export default function Markets({ d }: { d: Dashboard }) {
  const [kind, setKind] = useState("all");
  const rows = d.markets.filter((r) => kind === "all" || r.asset_class === kind);
  return (
    <Card title="Ranked markets" sub={`top ${d.markets.length} of ${d.scanned} scanned`} action={
      <div className="tabs">{KINDS.map((k) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{k}</button>)}</div>}>
      <div className="scroll">
        <table className="markets">
          <thead><tr><th>#</th><th>Market</th><th>Price</th><th>Today</th><th>Trend</th><th>Score</th><th>Signal</th><th title="How much trades each day">Liquidity</th><th title="Cost of crossing from bid to ask">Spread</th><th title="Money waiting within 1% of the price">Depth</th><th title="Buyers (+) or sellers (−) pushing">Flow</th><th>Open</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.symbol} title={(r.reasons ?? []).join(" ")}>
                <td className="muted">{i + 1}</td>
                <td><b>{r.symbol}</b><div className="muted small">{r.name}</div></td>
                <td>{price(r.price)}</td>
                <td><Pill value={r.change_pct} /></td>
                <td><Spark values={r.sparkline} /></td>
                <td><Meter value={r.score} /> {r.score.toFixed(2)}</td>
                <td><Tag tone={r.signal === "buy" ? "good" : r.signal === "sell" ? "bad" : ""}>{r.signal} {Math.round(r.confidence * 100)}%</Tag></td>
                <td><Meter value={r.liquidity} /></td>
                <td>{r.spread_bps.toFixed(1)} bp</td>
                <td>{r.depth_usd ? `$${(r.depth_usd / 1000).toFixed(0)}k` : "–"}</td>
                <td className={r.flow >= 0 ? "good-text" : "bad-text"}>{r.flow >= 0 ? "+" : ""}{r.flow.toFixed(2)}</td>
                <td>{r.open ? "●" : <span className="muted">closed</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
