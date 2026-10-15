/** One thread, opened from the Threads panel: what it said, its model kind, effort and sector (changing one teaches
 *  the picker, commander_pick.py), and a box to answer it or give it more work. A thread that is too full is restarted
 *  fresh with a summary when it gets more work; the view follows it to the new thread. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Markdown } from "../chat/Markdown";
import { QuestionDoneContext, QuestionSendContext } from "../chat/QuestionCard";
import { cap, tokensText, type CommanderState, type Thread } from "./ThreadsPanel";

interface Message { role: "user" | "assistant"; content: string }

/** The brief's standing instructions are for the thread's model, not for reading; the task above them is kept. */
function shown(text: string): string {
  return text.split("\n\n[Thread brief]")[0];
}

export function ThreadView({ thread, state, onBack, onChange, onFollow }: {
  thread: Thread; state: CommanderState | null; onBack: () => void; onChange: () => void; onFollow: (id: string) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const r = await api.get<{ messages: Message[] }>(`/api/chats/${thread.chat_id}/messages`);
    if (r.ok) setMessages(r.data.messages.slice(-60));
  }, [thread.chat_id]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 3000);
    return () => window.clearInterval(timer);
  }, [load]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length]);

  const change = async (body: Record<string, unknown>) => {
    setError("");
    const r = await api.put(`/api/commander/threads/${thread.id}`, body);
    if (!r.ok) setError(r.error); else onChange();
  };
  const send = async (typed?: string) => {
    const message = (typed ?? text).trim();
    if (!message) return;
    setSending(true); setError("");
    const r = await api.post<{ thread: Thread }>(`/api/commander/threads/${thread.id}/message`, { text: message });
    setSending(false);
    if (!r.ok) { setError(r.error); return; }
    if (typed === undefined) setText("");
    if (r.data.thread.id !== thread.id) onFollow(r.data.thread.id);  // it was full and started fresh
    onChange(); void load();
  };

  const answer = async (approve: boolean) => {
    const r = await api.post(`/api/approvals/${thread.approval_id}`, { approve });
    if (!r.ok) setError(r.error); else onChange();
  };

  const working = thread.status === "working" || Boolean(thread.approval_id);
  return (
    <section className="tv" aria-label={`Thread: ${thread.title}`}>
      <header className="tv-head">
        <button className="btn btn-secondary" onClick={onBack}>← Main chat</button>
        <div className="tv-title">
          <h2>{thread.title}</h2>
          <span className={`tv-status is-${thread.status}`}>{thread.status_label}</span>
        </div>
        <button className="btn btn-secondary" onClick={() => void change({ pinned: !thread.pinned })}>{thread.pinned ? "Unpin" : "Pin"}</button>
        <button className="btn btn-secondary" onClick={() => void change({ resolved: !thread.resolved })}>{thread.resolved ? "Reopen" : "Resolve"}</button>
      </header>
      <div className="tv-pick">
        <label>Model
          <select value={thread.tier} onChange={(e) => void change({ tier: e.target.value })}>
            {state?.kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
        </label>
        <label>Effort
          <select value={thread.effort} onChange={(e) => void change({ effort: e.target.value })}>
            {state?.efforts.map((e) => <option key={e} value={e}>{cap(e)}</option>)}
          </select>
        </label>
        <label>Job
          <select value={thread.job || "build"} onChange={(e) => void change({ job: e.target.value })}>
            {state?.jobs.map((j) => <option key={j} value={j}>{cap(j)}</option>)}
          </select>
        </label>
        <label>Sector
          <select value={thread.sector} onChange={(e) => void change({ sector: e.target.value })}>
            {state?.sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <span className="tv-why">
          {thread.model_label || "Router decides"} · {thread.source === "owner" ? "you chose it" : `picked because ${thread.why}`} · {tokensText(thread.tokens)}
          {thread.fresh_soon && " · starts fresh on its next task"}
        </span>
      </div>
      {thread.refreshed_from && <p className="tv-note">Started fresh from a fuller thread, with a summary of it.</p>}
      {thread.refreshed_to && <p className="tv-note"><button className="cx-chip" onClick={() => onFollow(thread.refreshed_to)}>This thread continues in a fresh one →</button></p>}
      <QuestionSendContext.Provider value={(answer) => void send(answer)}>
      <div className="tv-log">
        {messages.map((m, i) => (
          <div key={i} className={`tv-msg is-${m.role}`}>
            {m.role === "assistant" ? (
              // A card answered later (here, or relayed from the main chat) shows as answered, not as a fresh ask.
              <QuestionDoneContext.Provider value={messages.slice(i + 1).some((n) => n.role === "user") ? "Answered below" : null}>
                <Markdown text={m.content} />
              </QuestionDoneContext.Provider>
            ) : <p>{shown(m.content)}</p>}
          </div>
        ))}
        {working && <p className="tv-working"><span className="th-dot" aria-hidden="true" /> {thread.line || "Working"}</p>}
        {thread.approval_id && (
          <div className="tv-approve" role="group" aria-label="It is asking to go ahead">
            <span>It asks to go ahead: <b>{thread.line}</b></span>
            <button className="btn btn-primary" onClick={() => void answer(true)}>Approve</button>
            <button className="btn btn-secondary" onClick={() => void answer(false)}>Deny</button>
          </div>
        )}
        <div ref={end} />
      </div>
      </QuestionSendContext.Provider>
      {error && <p className="cx-error" role="alert">{error}</p>}
      <form className="tv-compose" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} disabled={working || sending}
          placeholder={working ? "It is working — answer when it is done" : thread.status === "needs_you" ? "Answer it here" : "Give this thread more work"}
          aria-label="Message this thread"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
        <button className="btn btn-primary" disabled={!text.trim() || working || sending}>Send</button>
      </form>
    </section>
  );
}
