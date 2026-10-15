// The first screen: how much money, which practice account, and start. A couple of clicks.
import { useEffect, useState } from "react";
import { api, type SetupView } from "../api";
import { Card, Tag } from "../ui";

export default function Setup({ owner, onDone }: { owner: boolean; onDone: () => void }) {
  const [s, setS] = useState<SetupView | null>(null);
  const [amount, setAmount] = useState("10000");
  const [currency, setCurrency] = useState("USD");
  const [broker, setBroker] = useState<"sim" | "alpaca">("sim");
  const [keys, setKeys] = useState({ key_id: "", secret_key: "" });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.setup().then((v) => {
    setS(v);
    setBroker(v.broker === "alpaca" ? "alpaca" : "sim");
    setCurrency(v.currency);
    setAmount(String(v.broker === "alpaca" && v.budget ? v.budget : v.start_cash));
  }).catch((e) => setNote(e.message));
  useEffect(() => { load(); }, []);

  const connect = async () => {
    setBusy(true);
    try { setNote((await api.connect("alpaca", keys)).note ?? "Connected."); setKeys({ key_id: "", secret_key: "" }); await load(); }
    catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };
  const save = async (start: boolean) => {
    setBusy(true);
    try {
      await api.saveSetup({ amount: Number(amount), currency, broker, start });
      setNote(start ? "Saved and started." : "Saved.");
      onDone();
    } catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };

  if (!s) return <div className="splash small">{note || "Loading setup…"}</div>;
  const needsKeys = broker === "alpaca" && !s.alpaca;
  return (
    <div className="grid setup">
      <Card title="1. How much money may it use?" sub={broker === "sim" ? "practice money" : "its share of the Alpaca account"} className="wide-2" accent>
        <div className="row">
          <input className="big" inputMode="decimal" value={amount} disabled={!owner} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} aria-label="Amount" />
          {broker === "sim" ? (
            <select value={currency} disabled={!owner} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
              {s.currencies.map((c) => <option key={c}>{c}</option>)}
            </select>
          ) : <Tag>USD</Tag>}
        </div>
        <div className="row chips">
          {[100, 1000, 10000, 100000].map((n) => <button key={n} className="ghost" disabled={!owner} onClick={() => setAmount(String(n))}>{n.toLocaleString()}</button>)}
        </div>
        <p className="small muted">The bots never use more than this, plus what they earn. No borrowing and no short selling.</p>
      </Card>
      <Card title="2. Which account?" className="wide-2">
        <div className="choices">
          <button className={`glass choice ${broker === "sim" ? "on" : ""}`} disabled={!owner} onClick={() => setBroker("sim")}>
            <b>Built-in practice</b><span className="small">Nothing to sign up for. Real prices, pretend money, real fees.</span>
          </button>
          <button className={`glass choice ${broker === "alpaca" ? "on" : ""}`} disabled={!owner} onClick={() => setBroker("alpaca")}>
            <b>Alpaca practice</b><span className="small">A free Alpaca account: stocks, ETFs and crypto, filled by Alpaca. {s.alpaca ? "Connected." : "Needs its free practice keys."}</span>
          </button>
        </div>
        {needsKeys && owner && (
          <form onSubmit={(e) => { e.preventDefault(); connect(); }}>
            <p className="small">Sign up free at alpaca.markets, open the <b>Paper</b> account, and copy its two keys here.</p>
            <input placeholder="API key ID (practice)" autoComplete="off" value={keys.key_id} onChange={(e) => setKeys({ ...keys, key_id: e.target.value })} />
            <input type="password" placeholder="Secret key (practice)" autoComplete="off" value={keys.secret_key} onChange={(e) => setKeys({ ...keys, secret_key: e.target.value })} />
            <button className="primary" type="submit" disabled={busy}>Connect Alpaca</button>
          </form>
        )}
        <p className="small muted">Real money is not switched on in this version.</p>
      </Card>
      <Card title="3. Go" className="wide-2">
        {owner ? (
          <div className="row">
            <button className="primary" disabled={busy || needsKeys || !Number(amount)} onClick={() => save(true)}>Save and start</button>
            <button className="ghost" disabled={busy || !Number(amount)} onClick={() => save(false)}>Just save</button>
          </div>
        ) : <p className="muted">Only the owner can change the setup.</p>}
        {note && <p className="small">{note}</p>}
        <p className="small muted">This computer: {s.cpus} cores, so it fetches {s.workers} prices at once. Everything else is in Tuning and Connectors.</p>
      </Card>
    </div>
  );
}
