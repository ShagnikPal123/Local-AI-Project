/** The two chat boxes.
 *
 * **The big one** goes to the top manager — *"Make a big text box which is where the main chat occurs. This is
 * given to a main manger who then communicates with all agents."* It also shows the phase the job is in, so the
 * owner can see planning turn into staffing turn into work.
 *
 * **The second one** is the aimed one — *"a second chat box where i can either click to select or say (in the
 * chat which agent group or which agents…)"*. Whatever is clicked in the bars and whatever is typed are resolved
 * together, live, and the line above the box says exactly who will receive it before it is sent.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Markdown } from "../../components/chat/Markdown";
import { officeApi, type Selection } from "./officeApi";
import type { Aim, OfficeAgent, OfficeJob, OfficeMessage, OfficeRole, OfficeSection } from "./types";

const PHASES: { id: string; label: string }[] = [
  { id: "plan", label: "Plan" },
  { id: "staff", label: "Staff" },
  { id: "brief", label: "Brief" },
  { id: "work", label: "Work" },
  { id: "review", label: "Review" },
  { id: "wrap", label: "Wrap up" },
];

function when(ts: number): string {
  if (!ts) return "";
  const date = new Date(ts * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Remember the height the owner dragged a box to.
 *
 * The CSS grip writes an inline height; this reads it back and puts it on again next time the tab is opened,
 * so "make the main chat taller" stays done. Nothing is stored until the owner actually resizes something.
 */
function useStoredHeight(key: string) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    try {
      const saved = Number(localStorage.getItem(key));
      if (saved >= 160) element.style.height = `${saved}px`;
    } catch {
      /* private browsing — the size simply will not persist */
    }
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      if (!element.style.height) return;                     // only once the owner has dragged the grip
      try {
        localStorage.setItem(key, String(Math.round(element.getBoundingClientRect().height)));
      } catch {
        /* ignored */
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [key]);
  return ref;
}

interface MainChatProps {
  messages: OfficeMessage[];
  job: OfficeJob | null;
  phase: string;
  running: boolean;
  onSend: (text: string) => Promise<void> | void;
  sending: boolean;
}

export function MainChat({ messages, job, phase, running, onSend, sending }: MainChatProps) {
  const [text, setText] = useState("");
  const list = useRef<HTMLDivElement | null>(null);
  const box = useStoredHeight("nyx.office.height.main");

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const send = async () => {
    const body = text.trim();
    if (!body || sending) return;
    setText("");
    await onSend(body);
  };

  return (
    <section className="ofc-chat ofc-chat--main" aria-label="Main chat with the top manager"
             ref={box as React.RefObject<HTMLElement>}>
      <header className="ofc-chat__head">
        <h2>Main chat</h2>
        <span className="ofc-chat__sub">Everything you say here goes to the top manager.</span>
        <span className="ofc-chat__grip" aria-hidden="true" title="Drag the bottom-right corner to resize" />
      </header>

      {(running || job) && (
        <ol className="ofc-phases" aria-label="What the office is doing">
          {PHASES.map((step) => (
            <li key={step.id} className={step.id === phase ? "is-now" : (PHASES.findIndex((p) => p.id === phase) >
              PHASES.findIndex((p) => p.id === step.id) ? "is-done" : "")}>
              {step.label}
            </li>
          ))}
        </ol>
      )}

      <div className="ofc-chat__list" ref={list}>
        {messages.length === 0 && (
          <div className="ofc-chat__empty">
            <p>Give the office something real to do.</p>
            <p className="ofc-muted">
              The top manager decides which sections exist, who is in them, and who does what — and you watch it
              happen on the floor. Try “Build me a landing page for a new product, with copy and three example
              designs”.
            </p>
          </div>
        )}
        {messages.map((message) => (
          <article key={message.id} className={`ofc-msg${message.by === "owner" ? " is-owner" : ""}`}>
            <header>
              <b>{message.by_name}</b>
              <time>{when(message.ts)}</time>
            </header>
            {message.by === "owner"
              ? <p className="ofc-msg__plain">{message.text}</p>
              : <Markdown text={message.text} />}
          </article>
        ))}
      </div>

      <div className="ofc-compose ofc-compose--big">
        <textarea value={text} rows={4} placeholder={running
          ? "The office is working — say anything and the top manager will fit it in…"
          : "What should the office work on?"}
          onChange={(event) => setText(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
          }} />
        <div className="ofc-compose__row">
          <span className="ofc-muted">Ctrl/⌘ + Enter sends</span>
          <button className="ofc-btn ofc-btn--primary" onClick={() => void send()} disabled={!text.trim() || sending}>
            {sending ? "Sending…" : running ? "Tell the office" : "Start the work"}
          </button>
        </div>
      </div>
    </section>
  );
}

interface TargetChatProps {
  officeId: string;
  messages: OfficeMessage[];
  selection: Selection;
  sections: Record<string, OfficeSection>;
  agents: Record<string, OfficeAgent>;
  roles: Record<string, OfficeRole>;
  focusSection: string;
  onSend: (text: string, aim: Aim | null) => Promise<void> | void;
  onDropChip: (kind: "sections" | "agents" | "roles", id: string) => void;
  onClear: () => void;
  sending: boolean;
}

export function TargetChat(props: TargetChatProps) {
  const { officeId, messages, selection, sections, agents, roles, focusSection } = props;
  const [text, setText] = useState("");
  const [aim, setAim] = useState<Aim | null>(null);
  const list = useRef<HTMLDivElement | null>(null);
  const box = useStoredHeight("nyx.office.height.target");

  const chips = useMemo(() => [
    ...selection.sections.map((id) => ({ kind: "sections" as const, id, label: sections[id]?.name ?? id,
      color: sections[id]?.color })),
    ...selection.roles.map((id) => ({ kind: "roles" as const, id, label: roles[id]?.plural ?? id,
      color: roles[id]?.color })),
    ...selection.agents.map((id) => ({ kind: "agents" as const, id, label: agents[id]?.name ?? id,
      color: roles[agents[id]?.role ?? ""]?.color })),
  ], [selection, sections, agents, roles]);

  // Live "who gets this" — offline on the server, so it can run on every keystroke.
  useEffect(() => {
    if (!officeId) return undefined;
    const timer = window.setTimeout(async () => {
      const result = await officeApi.resolve(officeId, text, selection, focusSection);
      if (result.ok) setAim(result.data);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [officeId, text, selection, focusSection]);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const send = async () => {
    const body = text.trim();
    if (!body || props.sending || !aim?.count) return;
    setText("");
    await props.onSend(body, aim);
  };

  return (
    <section className="ofc-chat ofc-chat--target" aria-label="Talk to chosen agents"
             ref={box as React.RefObject<HTMLElement>}>
      <header className="ofc-chat__head">
        <h2>Talk to…</h2>
        <span className="ofc-chat__sub">Click sections, kinds or agents — or just say who you mean.</span>
        <span className="ofc-chat__grip" aria-hidden="true" title="Drag the bottom-right corner to resize" />
      </header>

      <div className="ofc-aim">
        {chips.map((chip) => (
          <button key={`${chip.kind}-${chip.id}`} className="ofc-chip" style={{ ["--chip" as string]: chip.color }}
                  onClick={() => props.onDropChip(chip.kind, chip.id)} title="Remove">
            {chip.label} <span aria-hidden="true">✕</span>
          </button>
        ))}
        {chips.length > 0 && <button className="ofc-link" onClick={props.onClear}>clear</button>}
        <span className={`ofc-aim__who${aim && aim.count === 0 ? " is-empty" : ""}`}>
          {aim?.count ? `→ ${aim.label}` : chips.length || text.trim()
            ? "→ nobody yet — name a section, a kind of agent, or an agent"
            : "→ nobody selected"}
        </span>
      </div>

      <div className="ofc-chat__list" ref={list}>
        {messages.length === 0 && (
          <p className="ofc-muted ofc-chat__empty">
            Examples: “coder agents in every group: use tabs”, “managers: where are we?”, “optimizers of only
            Frontend and Data”, “Coder #2: rewrite the header”.
          </p>
        )}
        {messages.map((message) => (
          <article key={message.id} className={`ofc-msg ofc-msg--small${message.by === "owner" ? " is-owner" : ""}`}>
            <header>
              <b>{message.by_name}</b>
              {message.to_label && <span className="ofc-msg__to">→ {message.to_label}</span>}
              <time>{when(message.ts)}</time>
            </header>
            <p className="ofc-msg__plain">{message.text}</p>
          </article>
        ))}
      </div>

      <div className="ofc-compose">
        <textarea value={text} rows={2} placeholder="e.g. optimizers of only these groups: make the page load faster"
                  onChange={(event) => setText(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void send();
                    }
                  }} />
        <div className="ofc-compose__row">
          <span className="ofc-muted">Enter sends</span>
          <button className="ofc-btn" onClick={() => void send()}
                  disabled={!text.trim() || props.sending || !aim?.count}>
            {props.sending ? "Sending…" : `Send${aim?.count ? ` to ${aim.count}` : ""}`}
          </button>
        </div>
      </div>
    </section>
  );
}
