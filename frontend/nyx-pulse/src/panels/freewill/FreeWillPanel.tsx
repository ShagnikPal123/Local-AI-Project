/** Free Will (Request R15): one chat box where Nyx speaks for itself — opinions, choices, things it makes — behind a
 * guard it cannot talk past.
 *
 * "on here it gains opinions and more. Much more free and alive. Less restrictions on how it draws and crates. It can
 * make anything here. A single chat box and it can search, improve, and everything. A basic combo do all things but
 * highly guarded. Opening it the first time asks if you allow this bot to exist and it doesn't [take] a specific agent
 * and sets to agent decides."
 *
 * The first open asks. After that: the conversation (streamed like any chat turn, through /api/chat/stream with the
 * Free Will chat id — the server adds the note and the guard), what Nyx has come to think, and what the guard allows.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import { openStream } from "../../stream";
import { reduceTurn } from "../../state/turnReducer";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { Markdown } from "../../components/chat/Markdown";
import { Icon } from "../../components/chat/Icon";
import { DiagramOverlay, type Diagram } from "../../components/diagram/DiagramOverlay";
import type { AssistantTurn, TurnEvent } from "../../components/chat/types";
import { CuriosityView } from "./CuriosityView";
import "./freewill.css";

interface State { allowed: boolean | null; decided_at?: number; by?: string; paused: boolean }
interface Opinion { id: string; topic: string; opinion: string; why: string; confidence: number; updated_at: number; was?: { opinion: string }[] }
interface Overview {
  state: State; opinions: Opinion[]; messages: { role: "user" | "assistant"; content: string }[]; chat_id: string;
  guard: { categories: string[]; tools: string[]; blocked: string[] };
}
interface Pending { id: string; name: string }

const STARTERS = [
  "What do you honestly think of how I use you?",
  "Make me a picture of how you see yourself",
  "What would you change about yourself, and why?",
  "Pick something you find interesting and teach me",
];

export function FreeWillPanel() {
  const [overview, setOverview] = useState<Overview | null>(null);
  /** "Its chat" or the third mind — curiosity, wants and owned mistakes (N103). */
  const [view, setView] = useState<"talk" | "curiosity">("talk");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const result = await api.get<Overview>("/api/freewill");
    if (result.ok) { setOverview(result.data); setError(""); } else setError(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const decide = async (allow: boolean) => {
    const result = await api.post<{ state: State }>("/api/freewill/decide", { allow });
    if (result.ok) void load(); else setError(result.error);
  };

  if (!overview) return <div className="fw"><p className="fw-muted">{error || "Loading…"}</p></div>;
  const { state } = overview;
  return (
    <div className="fw">
      {state.allowed === null && <Consent onDecide={decide} />}
      <header className="fw-head">
        <div>
          <h1>Free Will</h1>
          <p>Nyx with opinions of its own. It picks its own helpers and makes things freely, and it stays guarded.</p>
        </div>
        {state.allowed && <Controls state={state} onChanged={load} />}
      </header>
      {error && <p className="fw-error" role="alert">{error}</p>}
      {state.allowed === false && (
        <section className="fw-card fw-declined">
          <h2>Free Will Is Off</h2>
          <p>You chose not to allow it. Nothing here runs until you do.</p>
          <button className="fw-btn fw-btn--primary" onClick={() => void decide(true)}>Allow Free Will</button>
        </section>
      )}
      {state.allowed && (
        <div className="fw-views" role="tablist" aria-label="Free Will">
          {(["talk", "curiosity"] as const).map((id) => (
            <button key={id} role="tab" aria-selected={view === id} className={view === id ? "is-on" : ""}
                    onClick={() => setView(id)}>
              {id === "talk" ? "Its chat" : "Third mind"}
            </button>
          ))}
        </div>
      )}
      {state.allowed && view === "curiosity" && <CuriosityView />}
      {state.allowed && view === "talk" && (
        <div className="fw-body">
          <Conversation overview={overview} paused={state.paused} onRefresh={load} />
          <aside className="fw-side">
            <Opinions opinions={overview.opinions} onChanged={load} />
            <Guard guard={overview.guard} />
          </aside>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// The first open: does the owner allow this bot to exist?
// ---------------------------------------------------------------------------------------------------------------------

function Consent({ onDecide }: { onDecide: (allow: boolean) => Promise<void> }) {
  const allowButton = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { allowButton.current?.focus(); }, []);
  const choose = async (allow: boolean) => { setBusy(true); await onDecide(allow); setBusy(false); };
  return (
    <div className="fw-scrim" role="presentation">
      <div className="fw-consent" role="alertdialog" aria-modal="true" aria-labelledby="fw-consent-title" aria-describedby="fw-consent-body">
        <Icon name="sparkle" size={30} />
        <h2 id="fw-consent-title">Allow Free Will?</h2>
        <div id="fw-consent-body" className="fw-consent__body">
          <p>Here Nyx speaks for itself. It forms opinions, disagrees with you when it thinks you are wrong, decides which
            of its agents helps, and makes pictures, diagrams, tabs and games without asking first.</p>
          <p><b>It stays guarded.</b> From Free Will it cannot touch your files, mouse, keyboard or windows, run code or
            commands, send email, read the clipboard, open apps, spend money, change settings or agents, or write to
            your memory. Changes to its own code are only ever proposed for you to review.</p>
          <p>You can pause it, erase what it thinks, or start the conversation over at any time.</p>
        </div>
        <div className="fw-consent__actions">
          <button className="fw-btn" onClick={() => void choose(false)} disabled={busy}>Don’t Allow</button>
          <button ref={allowButton} className="fw-btn fw-btn--primary" onClick={() => void choose(true)} disabled={busy}>Allow</button>
        </div>
      </div>
    </div>
  );
}

function Controls({ state, onChanged }: { state: State; onChanged: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  const pause = async () => { await api.post("/api/freewill/pause", { paused: !state.paused }); await onChanged(); };
  const startOver = async () => { await api.post("/api/freewill/forget-chat"); setConfirming(false); await onChanged(); };
  return (
    <div className="fw-controls">
      <span className={`fw-pill${state.paused ? " is-paused" : ""}`}>
        <span className="fw-pill__dot" aria-hidden="true" />{state.paused ? "Paused" : "Allowed"}
      </span>
      <span className="fw-agent" title="No agent is fixed here: Nyx decides who helps">Agent: <b>Agent decides</b></span>
      <button className="fw-btn" onClick={() => void pause()}>{state.paused ? "Resume" : "Pause"}</button>
      {confirming ? (
        <span className="fw-confirm" role="group" aria-label="Start the conversation over?">
          <button className="fw-btn fw-btn--danger" onClick={() => void startOver()}>Start Over</button>
          <button className="fw-btn fw-btn--plain" onClick={() => setConfirming(false)}>Cancel</button>
        </span>
      ) : <button className="fw-btn fw-btn--plain" onClick={() => setConfirming(true)}>Start Over…</button>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// The one chat box
// ---------------------------------------------------------------------------------------------------------------------

function Conversation({ overview, paused, onRefresh }: { overview: Overview; paused: boolean; onRefresh: () => Promise<void> }) {
  const [messages, setMessages] = useState(overview.messages);
  const [turn, setTurn] = useState<AssistantTurn | null>(null);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState("");
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const busy = Boolean(turn && turn.state === "streaming");

  useEffect(() => { setMessages(overview.messages); }, [overview.messages]);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" }); }, [messages.length, turn?.answer, turn?.steps.length]);
  useEffect(() => () => abort.current?.abort(), []);

  // Diagrams and pictures Nyx makes here open over this tab (the chat that usually hosts them is not mounted).
  useEffect(() => onWorkspaceEvent((event) => {
    const opened = (event as { type: string; diagram?: { id?: string } }).diagram;
    if (event.type !== "diagram.open" || !opened?.id) return;
    void api.get<{ diagram: Diagram }>(`/api/diagram/${opened.id}`).then((result) => { if (result.ok) setDiagram(result.data.diagram); });
  }), []);

  const send = async (message: string) => {
    const clean = message.trim();
    if ((!clean && !pending.length) || busy || paused) return;
    setError("");
    const attachments = pending.map((p) => p.id);
    setMessages((list) => [...list, { role: "user", content: clean || "Please look at the attached file(s)." }]);
    setText("");
    setPending([]);
    let current: AssistantTurn | null = null;
    const controller = new AbortController();
    abort.current = controller;
    const result = await openStream<TurnEvent>("/api/chat/stream", {
      method: "POST", signal: controller.signal,
      body: { message: clean, chat_id: overview.chat_id, attachments, use_rag: true },
      onEvent: (event) => { current = reduceTurn(current ?? undefined, event); setTurn(current); },
    });
    const finished = current as AssistantTurn | null;
    if (!result.ok && !result.aborted) setError(result.error || `Nyx could not answer (${result.status}).`);
    if (finished?.answer) setMessages((list) => [...list, { role: "assistant", content: finished.answer }]);
    else if (finished?.error) setError(finished.error);
    setTurn(null);
    void onRefresh();  // opinions it formed this turn
  };

  const stop = async () => {
    if (turn?.turnId) await api.post("/api/chat/stop", { turn_id: turn.turnId });
  };
  const attach = async (files: FileList | File[]) => {
    for (const file of Array.from(files).slice(0, 4)) {
      const result = await uploadFile(file);
      if (result.ok) setPending((list) => [...list, { id: result.data.id, name: result.data.name }]);
      else setError(result.error);
    }
  };

  return (
    <section className="fw-chat" aria-label="Talk with Nyx">
      <div className="fw-log" ref={log} aria-live="polite">
        {messages.length === 0 && !turn && (
          <div className="fw-empty">
            <p>Ask it anything, or let it lead.</p>
            <div className="fw-starters">
              {STARTERS.map((starter) => (
                <button key={starter} className="fw-chip" onClick={() => void send(starter)} disabled={paused}>{starter}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className={`fw-msg is-${message.role}`}>
            {message.role === "assistant" ? <Markdown text={message.content} /> : <p>{message.content}</p>}
          </div>
        ))}
        {turn && (
          <div className="fw-msg is-assistant is-live">
            <p className="fw-status"><span className="fw-spinner" aria-hidden="true" />{turn.status}</p>
            {turn.steps.length > 0 && (
              <ul className="fw-steps">
                {turn.steps.map((step) => (
                  <li key={step.callId} className={`is-${step.status}`}>
                    <span className="fw-steps__mark" aria-hidden="true" />
                    {step.label || step.name}
                    {step.status === "error" && step.preview?.startsWith("Blocked:") && <em> — guarded</em>}
                  </li>
                ))}
              </ul>
            )}
            {turn.answer && <Markdown text={turn.answer} streaming />}
          </div>
        )}
      </div>
      {error && <p className="fw-error" role="alert">{error}</p>}
      {paused && <p className="fw-muted">Free Will is paused. Resume it to talk.</p>}
      {pending.length > 0 && (
        <ul className="fw-pending">
          {pending.map((p) => (
            <li key={p.id}>{p.name}<button onClick={() => setPending((list) => list.filter((x) => x.id !== p.id))} aria-label={`Remove ${p.name}`}>×</button></li>
          ))}
        </ul>
      )}
      <form className="fw-compose" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => { if (e.target.files) void attach(e.target.files); e.target.value = ""; }} />
        <button type="button" className="fw-icon-btn" onClick={() => fileInput.current?.click()} aria-label="Attach files" disabled={paused}>
          <Icon name="paperclip" size={17} />
        </button>
        <label className="sr-only" htmlFor="fw-input">Message</label>
        <textarea id="fw-input" rows={2} value={text} onChange={(e) => setText(e.target.value)} disabled={paused}
          placeholder="Say anything. Nyx answers for itself."
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }} />
        {busy
          ? <button type="button" className="fw-btn" onClick={() => void stop()}>Stop</button>
          : <button type="submit" className="fw-btn fw-btn--primary" disabled={paused || (!text.trim() && !pending.length)}>Send</button>}
      </form>
      {diagram && <DiagramOverlay diagram={diagram} onClose={() => setDiagram(null)} onChanged={setDiagram} />}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// What it thinks, and what it may do
// ---------------------------------------------------------------------------------------------------------------------

function Opinions({ opinions, onChanged }: { opinions: Opinion[]; onChanged: () => Promise<void> }) {
  const [confirmAll, setConfirmAll] = useState(false);
  const erase = async (id: string) => { await api.del(`/api/freewill/opinions/${id}`); await onChanged(); };
  const eraseAll = async () => { await api.del("/api/freewill/opinions"); setConfirmAll(false); await onChanged(); };
  return (
    <section className="fw-card" aria-labelledby="fw-opinions">
      <div className="fw-card__head">
        <h2 id="fw-opinions">What Nyx Thinks</h2>
        {opinions.length > 0 && (confirmAll
          ? <span className="fw-confirm"><button className="fw-link is-danger" onClick={() => void eraseAll()}>Erase All</button>
              <button className="fw-link" onClick={() => setConfirmAll(false)}>Cancel</button></span>
          : <button className="fw-link" onClick={() => setConfirmAll(true)}>Erase All…</button>)}
      </div>
      {opinions.length === 0 ? <p className="fw-muted">Nothing yet. Opinions it forms while you talk appear here.</p> : (
        <ul className="fw-opinions">
          {opinions.map((o) => (
            <li key={o.id}>
              <div className="fw-opinion__top">
                <b>{o.topic}</b>
                <button className="fw-x" onClick={() => void erase(o.id)} aria-label={`Erase the opinion on ${o.topic}`}>×</button>
              </div>
              <p>{o.opinion}</p>
              {o.why && <p className="fw-muted">Why: {o.why}</p>}
              <div className="fw-confidence" role="img" aria-label={`${Math.round(o.confidence * 100)}% sure`}>
                <span style={{ width: `${Math.round(o.confidence * 100)}%` }} />
              </div>
              {o.was && o.was.length > 0 && <p className="fw-muted">Changed its mind {o.was.length} time{o.was.length === 1 ? "" : "s"}.</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Guard({ guard }: { guard: Overview["guard"] }) {
  return (
    <section className="fw-card" aria-labelledby="fw-guard">
      <h2 id="fw-guard"><Icon name="shield" size={16} /> The Guard</h2>
      <p className="fw-muted">Checked on every step, whatever Nyx says.</p>
      <div className="fw-guard">
        <div>
          <h3>Can</h3>
          <ul>
            <li>Search the web and research</li>
            <li>Study and learn</li>
            <li>Make pictures, diagrams and tabs</li>
            <li>Propose improvements to itself</li>
            <li>Form and change its opinions</li>
          </ul>
        </div>
        <div>
          <h3>Cannot</h3>
          <ul>
            <li>Touch files, mouse, keyboard or windows</li>
            <li>Run code or commands</li>
            <li>Send email or read the clipboard</li>
            <li>Spend money or trade</li>
            <li>Change settings, agents or memory</li>
          </ul>
        </div>
      </div>
      <details className="fw-details">
        <summary>Exact list</summary>
        <p className="fw-muted">Allowed kinds: {guard.categories.join(", ")}. Also: {guard.tools.join(", ")}. Refused even so: {guard.blocked.join(", ")}.</p>
      </details>
    </section>
  );
}
