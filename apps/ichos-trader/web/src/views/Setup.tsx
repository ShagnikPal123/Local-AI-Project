// The first screen: practice or real money, how much, which account, and start. A couple of clicks.
import { useEffect, useState } from "react";
import { api, money as fmt, type SetupView } from "../api";
import { Card, Tag } from "../ui";

type Mode = "practice" | "real";

export default function Setup({ owner, onDone, want }: { owner: boolean; onDone: () => void; want?: Mode }) {
  const [s, setS] = useState<SetupView | null>(null);
  const [mode, setMode] = useState<Mode>(want ?? "practice");
  const [amount, setAmount] = useState("10000");
  const [currency, setCurrency] = useState("USD");
  const [broker, setBroker] = useState<"sim" | "alpaca">("sim");
  const [keys, setKeys] = useState({ key_id: "", secret_key: "" });
  const [confirm, setConfirm] = useState("");
  const [dailyLoss, setDailyLoss] = useState("5");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.setup().then((v) => {
    setS(v);
    const real = want ?? (v.real_money.on ? "real" : "practice");
    setMode(real);
    setBroker(v.broker === "alpaca" ? "alpaca" : "sim");
    setCurrency(v.currency);
    setDailyLoss(String(v.real_money.daily_loss_pct));
    setAmount(String(real === "real" ? v.real_money.budget || 1000 : v.broker === "alpaca" && v.budget ? v.budget : v.start_cash));
  }).catch((e) => setNote(e.message));
  useEffect(() => { load(); }, []);

  const real = mode === "real";
  const pick = (to: Mode) => {  // each mode keeps its own amount: the real budget is not the practice cash
    setMode(to);
    if (s) setAmount(String(to === "real" ? s.real_money.budget || 1000 : s.broker === "alpaca" && s.budget ? s.budget : s.start_cash));
  };
  const connectId = real ? "alpaca_live" : "alpaca";
  const connect = async () => {
    setBusy(true);
    try { setNote((await api.connect(connectId, keys)).note ?? "Connected."); setKeys({ key_id: "", secret_key: "" }); await load(); setMode(real ? "real" : "practice"); }
    catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };
  const save = async (start: boolean) => {
    setBusy(true);
    try {
      await api.saveSetup({ amount: Number(amount), currency, broker: real ? "alpaca" : broker, start, money: mode,
        confirmation: confirm, daily_loss_pct: Number(dailyLoss) });
      setNote(start ? "Saved and started." : "Saved.");
      setConfirm("");
      onDone();
    } catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };
  const backToPractice = async () => {
    setBusy(true);
    try { await api.realMoneyOff(); setNote("Back on practice money. The trader is stopped; press Start when ready."); await load(); setMode("practice"); onDone(); }
    catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };

  if (!s) return <div className="splash small">{note || "Loading setup…"}</div>;
  const needsKeys = real ? !s.alpaca_live : broker === "alpaca" && !s.alpaca;
  const phraseOk = !real || confirm.trim().toLowerCase().replace(/\s+/g, " ") === s.real_money.confirmation.toLowerCase();
  return (
    <div className="grid setup">
      <Card title="Mode" sub={s.real_money.on ? "real money is on" : "practice is on"} className="wide-2">
        <div className="modes" role="radiogroup" aria-label="Mode">
          <button role="radio" aria-checked={!real} className={!real ? "on" : ""} disabled={!owner} onClick={() => pick("practice")}>
            <b>Practice</b><span className="small">Training money. Learn and test with nothing at risk.</span>
          </button>
          <button role="radio" aria-checked={real} className={real ? "on real" : ""} disabled={!owner} onClick={() => pick("real")}>
            <b>Real money</b><span className="small">Your Alpaca account, inside a budget you set. Fully automatic.</span>
          </button>
        </div>
        {s.real_money.on && owner && (
          <div className="row">
            <Tag tone="bad">Real money on · budget {fmt(s.real_money.budget)}</Tag>
            <button className="ghost" disabled={busy} onClick={backToPractice}>Switch back to practice</button>
          </div>
        )}
      </Card>

      <Card title={real ? "1. Budget: the most real money it may use" : "1. How much money may it use?"} sub={real ? "plus what it earns" : broker === "sim" ? "practice money" : "its share of the Alpaca practice account"} className="wide-2">
        <div className="row">
          <input className="big" inputMode="decimal" value={amount} disabled={!owner} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} aria-label="Amount" />
          {!real && broker === "sim" ? (
            <select value={currency} disabled={!owner} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
              {s.currencies.map((c) => <option key={c}>{c}</option>)}
            </select>
          ) : <Tag>USD</Tag>}
        </div>
        <div className="row chips">
          {(real ? [100, 500, 1000, 5000] : [100, 1000, 10000, 100000]).map((n) => <button key={n} className="ghost" disabled={!owner} onClick={() => setAmount(String(n))}>{n.toLocaleString()}</button>)}
        </div>
        {real ? (
          <label className="small">Stop for the day after losing <input className="tiny" inputMode="decimal" value={dailyLoss} disabled={!owner} onChange={(e) => setDailyLoss(e.target.value.replace(/[^0-9.]/g, ""))} aria-label="Daily loss limit" />% of the budget</label>
        ) : <p className="small muted">The bots never use more than this, plus what they earn. No borrowing and no short selling.</p>}
      </Card>

      <Card title="2. Which account?" className="wide-2">
        {real ? (
          <p className="small">Real money trades through <b>Alpaca</b> (stocks, ETFs and crypto). It uses the account's <b>live</b> keys, separate from practice keys, and only ever touches what it bought itself.</p>
        ) : (
          <div className="choices">
            <button className={`glass choice ${broker === "sim" ? "on" : ""}`} disabled={!owner} onClick={() => setBroker("sim")}>
              <b>Built-in practice</b><span className="small">Nothing to sign up for. Real prices, pretend money, real fees.</span>
            </button>
            <button className={`glass choice ${broker === "alpaca" ? "on" : ""}`} disabled={!owner} onClick={() => setBroker("alpaca")}>
              <b>Alpaca practice</b><span className="small">A free Alpaca account: stocks, ETFs and crypto, filled by Alpaca. {s.alpaca ? "Connected." : "Needs its free practice keys."}</span>
            </button>
          </div>
        )}
        {needsKeys && owner && (
          <form onSubmit={(e) => { e.preventDefault(); connect(); }}>
            <p className="small">{real ? "In Alpaca, open your live account's API keys and copy both here." : "Sign up free at alpaca.markets, open the Paper account, and copy its two keys here."}</p>
            <input placeholder={real ? "API key ID (live)" : "API key ID (practice)"} autoComplete="off" value={keys.key_id} onChange={(e) => setKeys({ ...keys, key_id: e.target.value })} />
            <input type="password" placeholder={real ? "Secret key (live)" : "Secret key (practice)"} autoComplete="off" value={keys.secret_key} onChange={(e) => setKeys({ ...keys, secret_key: e.target.value })} />
            <button className="primary" type="submit" disabled={busy}>{real ? "Connect live account" : "Connect Alpaca"}</button>
          </form>
        )}
        {!needsKeys && real && <Tag tone="good">Live account connected</Tag>}
      </Card>

      <Card title="3. Go" className="wide-2">
        {owner ? (
          <>
            {real && (
              <label className="small confirm"><span>Type <b>{s.real_money.confirmation}</b> to use real money</span>
                <input value={confirm} autoComplete="off" onChange={(e) => setConfirm(e.target.value)} aria-label="Confirmation" />
              </label>
            )}
            <div className="row">
              <button className={real ? "danger" : "primary"} disabled={busy || needsKeys || !Number(amount) || !phraseOk} onClick={() => save(true)}>{real ? "Use real money and start" : "Save and start"}</button>
              <button className="ghost" disabled={busy || needsKeys || !Number(amount) || !phraseOk} onClick={() => save(false)}>Just save</button>
            </div>
          </>
        ) : <p className="muted">Only the owner can change the setup.</p>}
        {note && <p className="small">{note}</p>}
        <p className="small muted">This computer: {s.cpus} cores, so it fetches {s.workers} prices at once. Everything else is in Tuning and Connectors.</p>
      </Card>
    </div>
  );
}
