/** One thing a thread sent up to its main chat (commander.sync_asks): a question card, a "Waiting on you" line or an
 *  approval, answered right here and relayed to the thread; or a finished result. Once answered, here or in the
 *  thread, it says where, so both places agree. The owner's ask (2026-10-14): threads talk to the main chat, where he
 *  mainly looks, and he can answer in either place. */

import { useState } from "react";
import { api } from "../../api";
import { Markdown } from "../chat/Markdown";
import { QuestionSendContext } from "../chat/QuestionCard";
import type { Ask } from "./ThreadsPanel";

export function AskRow({ ask, onOpen, onChange }: { ask: Ask; onOpen: (threadId: string) => void; onChange: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const answer = async (body: { text?: string; approve?: boolean }) => {
    setBusy(true); setError("");
    const r = await api.post(`/api/commander/asks/${ask.id}/answer`, body);
    setBusy(false);
    if (!r.ok) { setError(r.error); return; }
    setText(""); onChange();
  };

  const name = <button type="button" className="cmd-ask-name" onClick={() => onOpen(ask.thread_id)}>{ask.title}</button>;
  if (ask.kind === "result") {
    return <div className="cmd-ask is-result"><span className="th-dot" aria-hidden="true" /><p>{name} finished: {ask.line}</p></div>;
  }
  if (!ask.open) {
    return (
      <div className="cmd-ask is-closed">
        <span className="th-dot" aria-hidden="true" />
        <p>{name} asked: {ask.line}
          <span className="cmd-ask-where">{ask.where === "main" ? ` · You answered here: ${ask.answer}` : " · Answered in the thread"}</span></p>
      </div>
    );
  }
  return (
    <div className="cmd-ask is-open" role="group" aria-label={`${ask.title} needs you`}>
      <p><span className="th-dot" aria-hidden="true" /> {name} needs you{ask.kind === "approval" ? " to approve a step" : ""}</p>
      {ask.kind === "question" && ask.card ? (
        <QuestionSendContext.Provider value={(t) => void answer({ text: t })}><Markdown text={ask.card} /></QuestionSendContext.Provider>
      ) : ask.kind === "approval" ? (
        <div className="cmd-ask-row">
          <span>{ask.line}</span>
          <button className="btn btn-primary" disabled={busy} onClick={() => void answer({ approve: true })}>Approve</button>
          <button className="btn btn-secondary" disabled={busy} onClick={() => void answer({ approve: false })}>Deny</button>
        </div>
      ) : (
        <form className="cmd-ask-row" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void answer({ text }); }}>
          <span>{ask.line}</span>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Answer it here" aria-label={`Answer ${ask.title}`} />
          <button className="btn btn-primary" disabled={busy || !text.trim()}>Send</button>
        </form>
      )}
      {error && <p className="cx-error" role="alert">{error}</p>}
    </div>
  );
}
