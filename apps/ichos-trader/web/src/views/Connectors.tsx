// Brokers, data, models and logins. Keys go in once and only ever come back as their last 4.
import { useEffect, useState } from "react";
import { api, type Connector } from "../api";
import { Card, Tag } from "../ui";

const KIND: Record<string, string> = { broker: "Brokers", data: "Market data", model: "Models", login: "Sign-in" };

export default function Connectors({ owner }: { owner: boolean }) {
  const [rows, setRows] = useState<Connector[]>([]);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [note, setNote] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const load = () => api.connectors().then(setRows).catch((e) => setNote({ all: e.message }));
  useEffect(() => { load(); }, []);

  const connect = async (c: Connector) => {
    try {
      const done = await api.connect(c.id, values[c.id] ?? {});
      setNote((n) => ({ ...n, [c.id]: done.note ?? "Saved." }));
      setValues((v) => ({ ...v, [c.id]: {} }));
      load();
    } catch (e) { setNote((n) => ({ ...n, [c.id]: (e as Error).message })); }
  };
  const claude = rows.find((r) => r.id === "claude");

  return (
    <div className="grid connectors">
      {Object.entries(KIND).map(([kind, title]) => (
        <Card key={kind} title={title} className="wide-2">
          <div className="conns">
            {rows.filter((r) => r.kind === kind).map((c) => (
              <div key={c.id} className="glass conn">
                <div className="row"><b>{c.title}</b>{c.recommended && <Tag tone="info">recommended</Tag>}</div>
                <p className="small">{c.why}</p>
                <div className="row"><Tag tone={c.connected ? "good" : c.wired ? "" : "warn"}>{c.status}</Tag>
                  {c.money === "paid" && <Tag tone="warn">costs per use</Tag>}</div>
                {Object.entries(c.masked).map(([k, m]) => <div key={k} className="muted small">{k}: {m.last4 ?? "set"} ({m.from === "env" ? "from the computer's settings" : "saved"})</div>)}
                {owner && c.wired && c.fields.length > 0 && (
                  <form onSubmit={(e) => { e.preventDefault(); connect(c); }}>
                    {c.fields.map((f) => (
                      <input key={f.key} type={f.secret ? "password" : "text"} placeholder={f.label} autoComplete="off"
                        value={values[c.id]?.[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [c.id]: { ...v[c.id], [f.key]: e.target.value } }))} />
                    ))}
                    <div className="row">
                      <button className="primary" type="submit">{c.connected ? "Replace" : "Connect"}</button>
                      {c.connected && <button className="ghost" type="button" onClick={() => api.disconnect(c.id).then(load)}>Forget keys</button>}
                    </div>
                  </form>
                )}
                {note[c.id] && <p className="small muted">{note[c.id]}</p>}
              </div>
            ))}
          </div>
        </Card>
      ))}
      {owner && (
        <Card title="Ask Claude" sub="only when you press Ask" className="wide-2">
          {claude?.connected ? (
            <form onSubmit={(e) => { e.preventDefault(); setAnswer("Asking…"); api.ask(question).then((a) => setAnswer(a.answer)).catch((x) => setAnswer(x.message)); }}>
              <input placeholder="Why did it sell ETH?" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <button className="primary" type="submit">Ask</button>
            </form>
          ) : <p className="muted">Add a Claude key above to ask questions. The trader never calls Claude by itself.</p>}
          {answer && <p className="answer">{answer}</p>}
        </Card>
      )}
      {note.all && <p className="bad-text">{note.all}</p>}
    </div>
  );
}
