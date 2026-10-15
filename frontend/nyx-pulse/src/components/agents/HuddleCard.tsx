/** Team huddle (huddle.py, WS15): AI bots with human names and a bulb each, running a business together.
 *
 * The owner: "set it up for a business and have it push ai bots local and cloud to here and give them bulbs and human
 * names. They communicate here." Rounds run only when you press the button. With Slack connected and a channel set,
 * every message is also posted there.
 */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Member { id: string; name: string; role: string; runs: string; colour: string }
interface Message { id: string; author: string; member: string; text: string; at: number }
interface Huddle {
  business: { name: string; goal: string }; members: Member[]; messages: Message[];
  slack_channel: string; slack_connected: boolean;
}

export function HuddleCard() {
  const [h, setH] = useState<Huddle | null>(null);
  const [biz, setBiz] = useState({ name: "", goal: "", slack_channel: "" });
  const [bot, setBot] = useState({ name: "", role: "", runs: "cloud" });
  const [say, setSay] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const take = (r: { ok: boolean; data?: Huddle; error?: string }) => {
    if (r.ok && r.data) {
      setH(r.data);
      setBiz({ name: r.data.business.name, goal: r.data.business.goal, slack_channel: r.data.slack_channel });
      setNote("");
    } else setNote(r.error || "That didn't work.");
  };
  useEffect(() => { void api.get<Huddle>("/api/huddle").then(take); }, []);
  if (!h) return null;
  const colourOf = (m: Message) => h.members.find((x) => x.id === m.member)?.colour ?? "var(--color-neutral-500)";

  const run = async () => {
    setBusy("round");
    take(await api.post<Huddle>("/api/huddle/round", { rounds: 1 }));
    setBusy("");
  };

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 6 }}>Team huddle</div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 8, lineHeight: 1.5 }}>
        Bots with human names working one business together. Each speaks in turn when you run a round.
      </div>
      <form style={{ display: "grid", gap: 6, marginBottom: 10 }}
        onSubmit={async (e) => { e.preventDefault(); take(await api.put<Huddle>("/api/huddle", biz)); }}>
        <input className="text-input" placeholder="Business name" value={biz.name} aria-label="Business name"
          onChange={(e) => setBiz({ ...biz, name: e.target.value })} />
        <textarea className="text-input" rows={2} placeholder="What the business is trying to do" value={biz.goal}
          aria-label="Business goal" onChange={(e) => setBiz({ ...biz, goal: e.target.value })} />
        <input className="text-input" value={biz.slack_channel} aria-label="Slack channel id"
          placeholder={h.slack_connected ? "Slack channel id to mirror to (optional)" : "Connect Slack in Connectors to mirror the huddle there"}
          disabled={!h.slack_connected} onChange={(e) => setBiz({ ...biz, slack_channel: e.target.value })} />
        <button type="submit" className="btn btn-secondary">Save business</button>
      </form>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        {h.members.map((m) => (
          <span key={m.id} title={`${m.role} · runs ${m.runs === "local" ? "on this PC" : "in the cloud"}`}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, padding: "3px 8px",
              borderRadius: 999, background: "var(--color-surface-2)" }}>
            <span aria-hidden style={{ width: 9, height: 9, borderRadius: 999, background: m.colour, boxShadow: `0 0 8px ${m.colour}` }} />
            {m.name} · {m.role}
            <button type="button" className="btn btn-ghost" style={{ padding: "0 4px", fontSize: 11 }} aria-label={`Remove ${m.name}`}
              onClick={async () => take(await api.del<Huddle>(`/api/huddle/members/${m.id}`))}>×</button>
          </span>
        ))}
      </div>
      <form style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await api.post<Huddle>("/api/huddle/members", bot);
          take(r);
          if (r.ok) setBot({ name: "", role: "", runs: bot.runs });
        }}>
        <input className="text-input" style={{ flex: "1 1 110px" }} placeholder="Name, e.g. Maya" value={bot.name}
          aria-label="Bot name" onChange={(e) => setBot({ ...bot, name: e.target.value })} />
        <input className="text-input" style={{ flex: "2 1 160px" }} placeholder="Role, e.g. head of sales" value={bot.role}
          aria-label="Bot role" onChange={(e) => setBot({ ...bot, role: e.target.value })} />
        <select className="text-input" style={{ flex: "0 1 120px" }} value={bot.runs} aria-label="Where it runs"
          onChange={(e) => setBot({ ...bot, runs: e.target.value })}>
          <option value="cloud">Cloud</option>
          <option value="local">This PC</option>
        </select>
        <button type="submit" className="btn btn-secondary" disabled={!bot.name.trim()}>Add bot</button>
      </form>

      <div style={{ maxHeight: 320, overflowY: "auto", display: "grid", gap: 6, marginBottom: 8 }} aria-live="polite">
        {h.messages.length === 0 && <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>No messages yet.</div>}
        {h.messages.map((m) => (
          <div key={m.id} style={{ fontSize: 13, lineHeight: 1.5 }}>
            <b style={{ color: colourOf(m) }}>{m.author}</b> {m.text}
          </div>
        ))}
      </div>
      <form style={{ display: "flex", gap: 6 }}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!say.trim()) return;
          const r = await api.post<Huddle>("/api/huddle/post", { text: say });
          take(r);
          if (r.ok) setSay("");
        }}>
        <input className="text-input" style={{ flex: 1 }} placeholder="Say something to the team" value={say}
          aria-label="Message to the team" onChange={(e) => setSay(e.target.value)} />
        <button type="submit" className="btn btn-secondary" disabled={!say.trim()}>Post</button>
        <button type="button" className="btn btn-primary" disabled={busy === "round" || h.members.length === 0} onClick={() => void run()}>
          {busy === "round" ? "Talking…" : "Run a round"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={async () => take(await api.del<Huddle>("/api/huddle/messages"))}>Clear</button>
      </form>
      {note && <div role="status" style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 6 }}>{note}</div>}
    </div>
  );
}
