// The bot team: each bot's job, how much money it runs, how it is doing, and the manager's moves.
import { ago, money, type Dashboard } from "../api";
import { Bars } from "../charts";
import { Card, Pill, Tag } from "../ui";

const JOBS: Record<string, string> = {
  scout: "Fetches and ranks every market", strategist: "Studies history; learns before trading",
  advisor: "Matches each market to the strategy that worked", trader: "Buys and sells its share of the money",
  skeptic: "Stops or shrinks fishy buys", manager: "Moves money to what works; hires and retires",
  researcher: "Writes up the top pick",
};

export default function Team({ d }: { d: Dashboard }) {
  const traders = d.bots.filter((b) => b.role === "trader");
  const helpers = d.bots.filter((b) => b.role !== "trader");
  return (
    <div className="grid team">
      <Card title="Traders" sub="share of the money and results" className="wide-2">
        <div className="bots">
          {traders.map((b) => (
            <div key={b.id} className="glass bot">
              <div className="row"><b>{b.name}</b><Tag tone={b.status === "working" ? "good" : ""}>{b.status}</Tag></div>
              <div className="muted small">{b.classes.join(" + ")}{b.style === "rotate" ? " · rotates between the strongest" : ""}</div>
              <div className="big">{money(b.pot, d.money.currency)}</div>
              <div className="row"><span className="muted small">{Math.round(b.share * 100)}% · {b.trades} trades</span><Pill value={b.pl_pct} /></div>
              <p className="small">{b.doing}</p>
            </div>
          ))}
        </div>
        <Bars unit="%" items={traders.map((b) => ({ label: b.name, value: b.share * 100, hint: `${b.name} runs ${Math.round(b.share * 100)}% of the money` }))} />
      </Card>
      <Card title="Helpers" sub="the internal team">
        <ul className="list">
          {helpers.map((b) => (
            <li key={b.id}><span className={`dot ${b.status}`} /><b>{b.name}</b> <span className="muted">{b.role}</span>
              <p className="muted small">{JOBS[b.role] ?? ""}</p><p className="small">{b.doing}</p></li>
          ))}
        </ul>
      </Card>
      <Card title="Hires" sub="added by the manager">
        <ul className="list">
          {d.hires.slice().reverse().map((h) => <li key={h.name + h.at}><b>{h.name}</b> <span className="muted small">{ago(h.at)}</span><p className="small">{h.why}</p></li>)}
          {d.hires.length === 0 && <li className="muted">No hires yet. The manager adds a trader when a market has strong picks and nobody on it.</li>}
        </ul>
      </Card>
      <Card title="Skeptic's calls" sub="stopped or shrunk" className="wide-2">
        <ul className="notes">
          {d.thinking.filter((n) => n.role === "skeptic").slice(0, 15).map((n, i) => (
            <li key={i} className={`note ${n.level}`}><b>{n.symbol || n.bot}</b> <span className="muted">{ago(n.at)}</span><p>{n.text}</p></li>
          ))}
          {!d.thinking.some((n) => n.role === "skeptic") && <li className="muted">Nothing fishy so far.</li>}
        </ul>
      </Card>
    </div>
  );
}
