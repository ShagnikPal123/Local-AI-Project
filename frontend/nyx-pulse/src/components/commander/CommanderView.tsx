/** A Commander chat with its threads beside it (the owner's images p16 and p27): the main chat in the middle is the
 *  delegator, it hands the work out to threads, and the Threads panel on the right shows each one live. Opening a
 *  thread swaps the middle for that thread; "Main chat" comes back. Used by a project's page (Constellations), and
 *  ready for the chat's Commander mode. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Markdown } from "../chat/Markdown";
import { QuestionSendContext } from "../chat/QuestionCard";
import { ThreadView } from "./ThreadView";
import { ThreadsPanel, useCommander, type Thread } from "./ThreadsPanel";

interface Message { role: "user" | "assistant"; content: string }
interface TurnSummary { state: string; status: string }

export function CommanderView({ chatId, projectId = "", name }: { chatId: string; projectId?: string; name: string }) {
  const { state, error: boardError, reload } = useCommander(chatId, projectId);
  const [open, setOpen] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [turn, setTurn] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const r = await api.get<{ messages: Message[] }>(`/api/chats/${chatId}/messages`);
    if (r.ok) setMessages(r.data.messages.slice(-40));
  }, [chatId]);
  useEffect(() => { void load(); setOpen(""); }, [load]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length, status]);

  // While the main chat is handing work out, follow its turn's status line, then read the reply.
  useEffect(() => {
    if (!turn) return;
    const timer = window.setInterval(async () => {
      const r = await api.get<{ turn: TurnSummary }>(`/api/turns/${turn}`);
      if (!r.ok || r.data.turn.state !== "running") { setTurn(""); setStatus(""); void load(); void reload(); return; }
      setStatus(r.data.turn.status);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [turn, load, reload]);

  const send = async (typed?: string) => {
    const message = (typed ?? text).trim();
    if (!message) return;
    setError("");
    const r = await api.post<{ turn_id: string }>("/api/commander/send", { chat_id: chatId, message });
    if (!r.ok) { setError(r.error); return; }
    if (typed === undefined) setText("");
    setMessages((m) => [...m, { role: "user", content: message }]);
    setTurn(r.data.turn_id); setStatus("Starting");
  };

  const all = state?.board.groups.flatMap((g) => g.threads) ?? [];
  const thread = all.find((t) => t.id === open);
  const recent = [...all].sort((a, b) => b.updated - a.updated).slice(0, 3);
  const board = state?.board;

  return (
    <div className="cmd">
      <div className="cmd-main">
        {thread ? (
          <ThreadView thread={thread} state={state} onBack={() => setOpen("")} onChange={() => void reload()}
            onFollow={(id) => { setOpen(id); void reload(); }} />
        ) : (
          <section className="cmd-chat" aria-label={`${name}: main chat`}>
            <QuestionSendContext.Provider value={(answer) => void send(answer)}>
            <div className="cmd-log">
              <div className="cmd-intro">
                <h2>{name}</h2>
                <p>This is the main chat. Ask for anything here and it is split into threads that work side by side; this chat
                  stays clean and tells you who is doing what.</p>
                {board && board.total > 0 && (
                  <div className="cmd-context">
                    <span><b>{board.total}</b> threads</span>
                    <span><b>{board.needs_you}</b> need you</span>
                    <span><b>{board.working}</b> working</span>
                    {board.sectors.length > 0 && <span>Sectors: {board.sectors.join(", ")}</span>}
                  </div>
                )}
                {recent.length > 0 && (
                  <div className="cmd-recent">
                    <span className="cx-muted">Recent threads</span>
                    {recent.map((t) => <button key={t.id} className="cx-chip" onClick={() => setOpen(t.id)}>{t.title} ↩</button>)}
                  </div>
                )}
              </div>
              {messages.map((m, i) => (
                <div key={i} className={`tv-msg is-${m.role}`}>
                  {m.role === "assistant" ? <Markdown text={m.content} /> : <p>{m.content}</p>}
                </div>
              ))}
              {turn && <p className="tv-working"><span className="th-dot" aria-hidden="true" /> {status || "Handing it out"}</p>}
              <div ref={end} />
            </div>
            </QuestionSendContext.Provider>
            {(error || boardError) && <p className="cx-error" role="alert">{error || boardError}</p>}
            <form className="tv-compose" onSubmit={(e) => { e.preventDefault(); void send(); }}>
              <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} disabled={Boolean(turn)}
                placeholder={turn ? "Handing out the last request…" : "Ask for anything — it becomes threads"}
                aria-label="Message the main chat"
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
              <button className="btn btn-primary" disabled={!text.trim() || Boolean(turn)}>Send</button>
            </form>
          </section>
        )}
      </div>
      <ThreadsPanel state={state} onOpen={(t: Thread) => setOpen(t.id)} onChange={() => void reload()} />
    </div>
  );
}
