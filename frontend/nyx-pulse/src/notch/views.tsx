/** The views inside the open notch. Layouts and sizes follow Coucou's (SPEC §5); the agent-work, settings, timer,
 * sound and pinned-app views are Ichos's additions in the same style. */

import { useEffect, useMemo, useRef, useState } from "react";
import { IoView, MiniIo } from "./IoView";
import type { IoState } from "./io";
import type { AssistantSettings, CatalogAgent, FileRead, NotchAgent, Pinned, Timer, Work, WorkStep } from "./notchApi";

// ── Icons (stroke, currentColor) ────────────────────────────────────────────

const svg = (d: React.ReactNode, size = 15, fill = false) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"}
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
export const Icon = {
  home: () => svg(<path d="M3.5 10.6 12 3.8l8.5 6.8V20a1 1 0 0 1-1 1h-5v-6.2h-5V21h-5a1 1 0 0 1-1-1z" />, 14, true),
  chat: () => svg(<path d="M5 4h14a2.5 2.5 0 0 1 2.5 2.5v8A2.5 2.5 0 0 1 19 17h-7.3L7 20.6V17H5a2.5 2.5 0 0 1-2.5-2.5v-8A2.5 2.5 0 0 1 5 4z" />, 14, true),
  plus: () => svg(<path d="M12 5v14M5 12h14" />, 15),
  gear: () => svg(<><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" /></>, 16),
  sound: (muted: boolean) => svg(<><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" />{muted
    ? <path d="m16 9.5 5 5M21 9.5l-5 5" />
    : <><path d="M15.5 9a4 4 0 0 1 0 6" /><path d="M18.3 6.5a7.5 7.5 0 0 1 0 11" /></>}</>, 16),
  back: () => svg(<><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></>, 15),
  close: () => svg(<path d="M6 6l12 12M18 6 6 18" />, 15),
  mic: () => svg(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></>, 14),
  send: () => svg(<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />, 14),
  check: () => svg(<path d="m5 12.5 4.2 4L19 7" />, 10),
  file: () => svg(<><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /></>, 13),
  edit: () => svg(<path d="M4 20h4L19 9l-4-4L4 16z" />, 13),
  term: () => svg(<path d="m5 8 4 4-4 4M12 16h7" />, 13),
  mail: () => svg(<><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m4 7 8 6 8-6" /></>, 13),
  search: () => svg(<><circle cx="11" cy="11" r="6" /><path d="m20 20-4.2-4.2" /></>, 13),
  bolt: () => svg(<path d="M13 2 4 14h7l-1 8 9-12h-7z" />, 12, true),
};

export function agentIoState(agent?: NotchAgent | null): IoState {
  if (!agent) return "idle";
  return ({ working: "working", thinking: "thinking", approval: "approval", error: "error", finished: "finished" } as
    Record<string, IoState>)[agent.state] ?? "idle";
}

function pillStyle(color: string): React.CSSProperties {
  return { ["--pc-a" as string]: `${color}21`, ["--pc-b" as string]: `${color}52`, ["--pc-t" as string]: lighten(color) };
}

function lighten(hex: string): string {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * 0.25);
  return `rgb(${mix((n >> 16) & 255)},${mix((n >> 8) & 255)},${mix(n & 255)})`;
}

// ── Home (overview) ─────────────────────────────────────────────────────────

export function HomeView(props: {
  agents: NotchAgent[]; focus: NotchAgent; pinned: Pinned[]; ioImage: string; ioName: string;
  onFocus: (id: string) => void; onOpenWork: () => void; onAdd: () => void; onAsk: () => void;
  onDropAgent: (id: string) => void; recent: WorkStep | null; ioState: IoState; clock: string;
}) {
  const { focus, agents } = props;
  const [hot, setHot] = useState(false);
  const others = agents.filter((a) => a.id !== focus.id);
  const isIchos = focus.kind === "ichos";
  const ticker = useTicker(focus);
  const accepts = (e: React.DragEvent) => e.dataTransfer.types.includes("application/x-ichos-agent");
  return (
    <div className="nx-overview">
      <div className="left">
        <div className="nx-card wash" style={{ ["--wash" as string]: isIchos ? "rgba(165,148,255,.22)" : `${focus.color}55` }}
          onClick={isIchos ? undefined : props.onOpenWork}>
          <div className="nx-focus">
            <IoView size={58} state={isIchos ? props.ioState : agentIoState(focus)} tint={isIchos ? "" : focus.color}
              image={isIchos ? props.ioImage : ""} />
            <div className="nx-grow">
              <div className="nx-row who">
                <span className="nx-dot" style={{ background: isIchos ? "#A594FF" : focus.color }} />
                <span className="who">{isIchos ? props.ioName : focus.name}<small>{isIchos ? "Ichos" : focus.sub ?? kindLabel(focus.kind)}</small></span>
                {!isIchos && focus.count ? <span className="count">{Math.min(focus.count, 99)} steps</span> : null}
              </div>
              {isIchos ? (
                <>
                  <div className="nx-big" style={{ marginTop: 2 }}>{props.clock}</div>
                  <div className="nx-sub nx-ellipsis" style={{ marginTop: 2 }}>
                    {props.recent ? props.recent.title : others.length ? `${others.length} agent${others.length > 1 ? "s" : ""} with you` : "Nothing running right now."}
                  </div>
                  <div style={{ marginTop: 8 }}><button className="nx-btn small primary" onClick={props.onAsk}>Ask {props.ioName}</button></div>
                </>
              ) : (
                <>
                  <div className="nx-ticker">
                    {ticker.map((row, i) => (
                      <div key={`${row}-${i}`} className={`nx-ticker-row ${i === 1 ? "current" : ""}`}>
                        {i === 1 ? <span className={focus.state === "working" ? "nx-shimmer" : ""}>{row}</span> : row}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="right">
        <div className="nx-card">
          <div className="nx-pills"
            onDragOver={(e) => { if (accepts(e)) { e.preventDefault(); setHot(true); } }}
            onDragLeave={() => setHot(false)}
            onDrop={(e) => {
              setHot(false);
              const id = e.dataTransfer.getData("application/x-ichos-agent");
              if (id) props.onDropAgent(id);
            }}>
            {[...props.pinned.map((p) => ({ id: `pin:${p.id}`, name: p.name, color: p.color, state: "idle" as const, pinned: true })),
              ...others.map((a) => ({ id: a.id, name: a.name, color: a.color, state: a.state, pinned: false }))].slice(0, 3).map((p) => (
              <button key={p.id} className="nx-pill" style={pillStyle(p.color)} onClick={() => props.onFocus(p.id)} title={p.name}>
                <MiniIo color={p.color} size={24} state={p.state === "working" ? "working" : "idle"} />
                <span className="lbl">{p.name}</span>
              </button>
            ))}
            <button className={`nx-pill add ${hot ? "drop-hot" : ""}`} onClick={props.onAdd}>{hot ? "Drop to add" : others.length + props.pinned.length > 3 ? `+${others.length + props.pinned.length - 3} more` : "+ Agent"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function kindLabel(kind: string): string {
  return ({ avatar: "Avatar", agent: "Agent", claude: "Claude Code", ichos: "Ichos" } as Record<string, string>)[kind] ?? kind;
}

/** Previous, current, next rows of the focused agent's work; scrolls up as new steps arrive. */
function useTicker(agent: NotchAgent): string[] {
  const [rows, setRows] = useState<string[]>(["", agent.step || "Starting", ""]);
  useEffect(() => {
    setRows((old) => (old[1] === agent.step ? old : [old[1], agent.step || "Working", ""]));
  }, [agent.step]);
  return rows;
}

/** Coucou's "empty": nothing is running — Io sits in the middle among the stars. */
export function EmptyView({ ioState, ioImage, onClick }: { ioState: IoState; ioImage: string; onClick: () => void }) {
  return (
    <div className="nx-card stars" style={{ display: "grid", placeItems: "center" }}>
      <IoView size={62} state={ioState} image={ioImage} className="big" onClick={onClick} title="Ask Ichos" />
    </div>
  );
}

// ── Chat ────────────────────────────────────────────────────────────────────

export interface ChatEntry { role: "user" | "assistant"; text: string; steps?: string[]; done?: boolean }

export function ChatView(props: {
  log: ChatEntry[]; busy: boolean; ultrafast: boolean; files: { id: string; name: string }[]; ioState: IoState;
  ioImage: string; ioName: string; onSend: (text: string) => void; onToggleUltra: () => void; onActivity: () => void;
  levels?: () => number[];
}) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const recog = useRef<{ stop: () => void } | null>(null);
  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [props.log]);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    setText("");
    props.onSend(value);
  };

  const dictate = () => {
    if (listening) {
      recog.current?.stop();
      return;
    }
    const w = window as unknown as { SpeechRecognition?: new () => SpeechLike; webkitSpeechRecognition?: new () => SpeechLike };
    const Speech = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Speech) return;
    const r = new Speech();
    r.interimResults = true;
    r.lang = navigator.language || "en-US";
    r.onresult = (event) => {
      const said = Array.from(event.results).map((res) => res[0].transcript).join("");
      setText(said);
      if (event.results[event.results.length - 1].isFinal) {
        r.stop();
        props.onSend(said.trim());
        setText("");
      }
    };
    r.onend = () => setListening(false);
    recog.current = r;
    setListening(true);
    r.start();
  };

  return (
    <div className="nx-card">
      <span style={{ position: "absolute", left: 30, bottom: 12 }}>
        <IoView size={44} state={listening ? "listening" : props.busy ? "thinking" : props.ioState} image={props.ioImage} levels={props.levels} />
      </span>
      <div className="nx-chat">
        <button className="nx-chip" onClick={props.onToggleUltra} title="Ultra Fast: desktop commands done at once (Jev-style)">
          <span className="nx-dot" style={{ background: props.ultrafast ? "#F5A524" : "#34D399" }} />
          {props.ultrafast ? <>{Icon.bolt()} Ultra Fast</> : props.ioName}
        </button>
        <div className="nx-log" ref={logRef}>
          {props.log.map((m, i) => (
            <div key={i} className={`nx-msg ${m.role}`}>
              {m.role === "assistant" && !m.done && m.steps?.length ? <span className="step">{m.steps[m.steps.length - 1]}</span> : null}
              {m.text || (m.role === "assistant" && !m.done ? <span className="nx-shimmer">Thinking…</span> : "")}
            </div>
          ))}
        </div>
        {props.files.length ? <div className="nx-attach">{props.files.map((f) => <span key={f.id}>{f.name}</span>)}</div> : null}
        <div className="nx-input">
          <input ref={input} value={text} placeholder={props.files.length ? "Ask about it, or say “send it to …”" : `Ask ${props.ioName}…`}
            onChange={(e) => { setText(e.target.value); props.onActivity(); }}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }} aria-label="Message" />
          <button className={`nx-round ${listening ? "live" : ""}`} onClick={dictate} aria-label="Speak">{Icon.mic()}</button>
          <button className="nx-round primary" onClick={submit} aria-label="Send" disabled={!text.trim()}>{Icon.send()}</button>
        </div>
      </div>
    </div>
  );
}

interface SpeechLike {
  interimResults: boolean;
  lang: string;
  onresult: (event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void;
  onend: () => void;
  start: () => void;
  stop: () => void;
}

// ── Files: drop → uploading → ready → email → sent ─────────────────────────

export function DropView({ onFiles, hot }: { onFiles: (files: File[]) => void; hot: boolean }) {
  const picker = useRef<HTMLInputElement>(null);
  return (
    <div className={`nx-drop ${hot ? "hot" : ""}`} onClick={() => picker.current?.click()}>
      <span style={{ position: "absolute", left: 44, top: "50%", transform: "translateY(-50%)" }}>
        <IoView size={62} state={hot ? "listening" : "idle"} emote={hot ? { name: "surprised", at: 1 } : null} />
      </span>
      <div>
        <h3>Drop your files here</h3>
        <div className="nx-tags"><span>PDF</span><span>Images</span><span>Code</span><span>Docs</span><span>Sheets</span></div>
      </div>
      <input ref={picker} type="file" multiple hidden onChange={(e) => onFiles(Array.from(e.target.files ?? []))} />
    </div>
  );
}

export function UploadingView({ name, percent }: { name: string; percent: number }) {
  return (
    <div className="nx-upload">
      <div className="line"><span>Uploading {name}</span><span>{Math.round(percent)} %</span></div>
      <div className="nx-bar">
        <i style={{ width: `${percent}%` }} />
        <span className="nx-io" style={{ left: `${percent}%`, width: 24, height: 24, position: "absolute" }}>
          <IoView size={22} state="working" details={false} />
        </span>
      </div>
    </div>
  );
}

export function ChooseView({ read, names, onAsk, onEmail }: { read: FileRead | null; names: string; onAsk: () => void; onEmail: () => void }) {
  return (
    <div className="nx-card wash" style={{ ["--wash" as string]: "rgba(52,211,153,.4)" }}>
      <div className="nx-split">
        <IoView size={52} state="finished" emote={{ name: "happy", at: 1 }} />
        <div className="nx-grow">
          <div className="nx-title nx-ellipsis">{names} is ready.</div>
          <div className="nx-sub nx-ellipsis">{read?.summary || "What do you want to do with it?"}</div>
          {read?.report ? (
            <div className="nx-report">
              {read.report.categories.slice(0, 4).map((c) => <span key={c.name}>{c.name} {c.amount.toLocaleString()}</span>)}
            </div>
          ) : null}
          <div className="nx-row" style={{ marginTop: 10, gap: 8 }}>
            <button className="nx-btn primary" onClick={onAsk}>Ask a question about it</button>
            <button className="nx-btn" onClick={onEmail}>Send by email</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function MailView(props: {
  fileName: string; draft: { to: string; subject: string; body: string }; sending: boolean; error: string;
  onChange: (draft: { to: string; subject: string; body: string }) => void; onSend: () => void; onCancel: () => void;
}) {
  const { draft } = props;
  return (
    <div className="nx-card">
      <div className="nx-split" style={{ alignItems: "flex-start", paddingTop: 10 }}>
        <span style={{ marginTop: 40 }}><IoView size={46} state={props.sending ? "working" : "idle"} /></span>
        <div className="nx-fields">
          <div className="nx-row"><span className="nx-title" style={{ fontSize: 13 }}>New email</span>
            {props.fileName ? <span className="nx-sub">with {props.fileName}</span> : null}</div>
          <div className="nx-field"><label htmlFor="nx-to">To</label>
            <input id="nx-to" value={draft.to} autoFocus onChange={(e) => props.onChange({ ...draft, to: e.target.value })} /></div>
          <div className="nx-field"><label htmlFor="nx-subject">Subject</label>
            <input id="nx-subject" value={draft.subject} onChange={(e) => props.onChange({ ...draft, subject: e.target.value })} /></div>
          <div className="nx-field area">
            <textarea aria-label="Message" value={draft.body} placeholder="Message (optional)"
              onChange={(e) => props.onChange({ ...draft, body: e.target.value })} /></div>
          <div className="nx-row" style={{ gap: 8 }}>
            <button className="nx-btn primary" onClick={props.onSend} disabled={props.sending || !draft.to.trim()}>
              {props.sending ? "Sending…" : "Send"}</button>
            <button className="nx-btn" onClick={props.onCancel}>Cancel</button>
            {props.error ? <span className="nx-sub" style={{ color: "var(--red-text)" }}>{props.error}</span> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export function NoteView({ text, tone, ioImage }: { text: string; tone: "good" | "bad" | "plain"; ioImage: string }) {
  const wash = tone === "good" ? "rgba(52,211,153,.42)" : tone === "bad" ? "rgba(244,80,94,.5)" : "rgba(255,255,255,.08)";
  return (
    <div className="nx-card wash" style={{ ["--wash" as string]: wash }}>
      <div className="nx-split">
        <IoView size={50} state={tone === "bad" ? "error" : "idle"} emote={tone === "good" ? { name: "wink", at: Date.now() } : null} image={ioImage} />
        <div className="nx-title" style={{ fontSize: 13.5 }}>{text}</div>
      </div>
    </div>
  );
}

// ── An agent's live work: code as it is written, the email as it is drafted ──

export function WorkView({ agent, work, onTask, onStop }: {
  agent: NotchAgent; work: Work | null; onTask: (text: string) => void; onStop: () => void;
}) {
  const [text, setText] = useState("");
  const steps = work?.steps ?? [];
  const lastEdit = [...steps].reverse().find((s) => s.kind === "edit");
  const lastMail = [...steps].reverse().find((s) => s.kind === "email");
  const lastBash = [...steps].reverse().find((s) => s.kind === "bash");
  const running = work?.status === "running";
  const checks = useMemo(() => {
    const kinds = ["read", "edit", "bash", "done"];
    const seen = new Set<string>(steps.map((s) => s.kind));
    const labels: Record<string, string> = { read: "Read", edit: "Edit", bash: "Run", done: "Done" };
    const current = steps.length ? steps[steps.length - 1].kind : "";
    return (work?.work === "email" ? ["read", "email", "done"] : kinds).map((k) => ({
      k, label: labels[k] ?? "Email", state: seen.has(k) ? (k === current && running ? "live" : "ok") : "todo",
    }));
  }, [steps, running, work?.work]);
  const ioState: IoState = running ? "working" : work?.status === "error" ? "error" : work?.status === "done" ? "finished" : "idle";

  return (
    <div className="nx-work">
      <div className="nx-work-side">
        <IoView size={56} state={ioState} tint={agent.kind === "ichos" ? "" : agent.color} />
        <div className="name nx-ellipsis">{agent.name}</div>
        <div className="nx-sub" style={{ marginTop: -2 }}>{agent.sub ?? kindLabel(agent.kind)}</div>
        <div className="nx-checks">
          {checks.map((c) => (
            <div key={c.k} className={`nx-check ${c.state}`}><span className="box">{c.state === "ok" ? Icon.check() : null}</span>{c.label}</div>
          ))}
        </div>
      </div>
      <div className="nx-code">
        {work?.work === "email" && lastMail?.email ? (
          <>
            <div className="nx-code-head">{Icon.mail()}<span>{lastMail.email.subject || "New email"}</span>
              {running ? <span className="mod" /> : null}<span className="path">draft</span></div>
            <div className="nx-mail">
              <div className="hdr">To <b>{lastMail.email.to}</b></div>
              <div className="hdr">Subject <b>{lastMail.email.subject}</b></div>
              <div className="body">{lastMail.email.body}{running ? <span className="nx-caret" /> : null}</div>
            </div>
          </>
        ) : lastEdit ? (
          <>
            <div className="nx-code-head">
              {/\.(ts|tsx)$/.test(lastEdit.file ?? "") ? <span className="ts">TS</span> : Icon.file()}
              <span>{(lastEdit.file ?? "").split(/[\\/]/).pop()}</span>{running ? <span className="mod" /> : null}
              <span className="path">{shortPath(lastEdit.file ?? "")}</span>
            </div>
            <div className="nx-code-body">
              {(lastEdit.diff ?? []).map((line, i) => (
                <div key={i} className={`nx-line ${line.sym === "+" ? "add" : line.sym === "-" ? "rem" : ""}`}>
                  <span className="no">{line.no}</span><span className="sym">{line.sym === " " ? "" : line.sym}</span>
                  <span className="txt">{line.text}</span>
                </div>
              ))}
              {lastBash || running ? (
                <div className="nx-line term"><span className="no" /><span className="sym" style={{ color: "#34D399" }}>$</span>
                  <span className="txt">{lastBash?.command ?? ""}{running ? <span className="nx-caret" /> : null}</span></div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="nx-steps">
            {work?.task ? <div className="nx-step"><span className="k">Task</span><span>{work.task}</span></div> : null}
            {steps.slice(-8).map((s, i) => (
              <div key={i} className="nx-step"><span className="k">{s.kind === "note" ? "" : s.kind}</span>
                <span className={i === Math.min(7, steps.length - 1) && running ? "nx-shimmer" : ""}>{s.title}</span></div>
            ))}
            {!steps.length ? <div className="nx-sub">Give {agent.name} a task below — you'll see the work here as it happens.</div> : null}
            {work?.result && !running ? <div className="nx-msg" style={{ marginTop: 6 }}>{work.result.slice(0, 600)}</div> : null}
          </div>
        )}
        <div className="nx-input" style={{ margin: 6, height: 32 }}>
          <input value={text} placeholder={running ? `${agent.name} is working…` : `Ask ${agent.name} to…`}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onTask(text.trim()); setText(""); } }} aria-label="Task" />
          {running && work?.id ? <button className="nx-btn small danger" onClick={onStop}>Stop</button>
            : <button className="nx-round primary" aria-label="Start" onClick={() => { if (text.trim()) { onTask(text.trim()); setText(""); } }}>{Icon.send()}</button>}
        </div>
      </div>
    </div>
  );
}

function shortPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join("/");
}

// ── Pick an agent, or make a new one ───────────────────────────────────────

export function AgentsView({ catalog, onPick, onNew }: {
  catalog: CatalogAgent[]; onPick: (id: string) => void; onNew: (name: string, task: string) => void;
}) {
  const [name, setName] = useState("");
  const [task, setTask] = useState("");
  return (
    <div className="nx-card">
      <div className="nx-list">
        <div className="nx-item">
          <MiniIo color="#A594FF" size={24} />
          <input className="nx-grow" style={inputStyle} placeholder="New agent's name" value={name} onChange={(e) => setName(e.target.value)} aria-label="New agent name" />
          <input className="nx-grow" style={inputStyle} placeholder="…and its first task" value={task} onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim() && task.trim()) onNew(name.trim(), task.trim()); }} aria-label="First task" />
          <button className="nx-btn small primary" disabled={!name.trim() || !task.trim()} onClick={() => onNew(name.trim(), task.trim())}>Start</button>
        </div>
        {catalog.map((a) => (
          <div key={a.id} className="nx-item" draggable onDragStart={(e) => e.dataTransfer.setData("application/x-ichos-agent", a.id)}
            onClick={() => onPick(a.id)} role="button" tabIndex={0}>
            <MiniIo color={a.color} size={24} />
            <div className="nx-grow">
              <div className="nx-title" style={{ fontSize: 12.5 }}>{a.name}</div>
              <div className="about nx-ellipsis">{a.about || a.kind}</div>
            </div>
            <span className="nx-sub" style={{ fontSize: 11 }}>{kindLabel(a.kind)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  border: 0, outline: 0, background: "rgba(255,255,255,.05)", color: "var(--ink)", borderRadius: 9, height: 28,
  padding: "0 10px", font: "400 12.5px var(--font)", minWidth: 0,
};

// ── Assistant settings (the gear) ───────────────────────────────────────────

export function SettingsView({ settings, onSave, onOpenSetup }: {
  settings: AssistantSettings; onSave: (changes: Partial<AssistantSettings>) => void; onOpenSetup: () => void;
}) {
  const s = settings;
  const toggle = (on: boolean, change: () => void, label: string) => (
    <button className={`nx-switch ${on ? "on" : ""}`} onClick={change} aria-label={label} aria-pressed={on} />
  );
  return (
    <div className="nx-card">
      <div className="nx-list" style={{ gap: 2 }}>
        <div className="nx-set"><span className="nx-grow">Talk to Ichos out loud</span>
          {toggle(s.talk, () => onSave({ talk: !s.talk }), "Talk")}</div>
        <div className="nx-set"><span className="nx-grow">Open when the pointer rests on the notch</span>
          {toggle(s.notch.open_on_hover, () => onSave({ notch: { ...s.notch, open_on_hover: !s.notch.open_on_hover } }), "Open on hover")}</div>
        <div className="nx-set"><span className="nx-grow">Split into three notches (app · clock · sound)</span>
          {toggle(s.notch.trio, () => onSave({ notch: { ...s.notch, trio: !s.notch.trio } }), "Three notches")}</div>
        <div className="nx-set"><span className="nx-grow">Ultra Fast — desktop commands at once</span>
          {toggle(s.ultrafast, () => onSave({ ultrafast: !s.ultrafast }), "Ultra Fast")}</div>
        <div className="nx-set"><span className="nx-grow">Sound notch shows</span>
          <span className="nx-seg">
            <button className={s.sound.mode === "ai" ? "on" : ""} onClick={() => onSave({ sound: { ...s.sound, mode: "ai" } })}>Ichos's voice</button>
            <button className={s.sound.mode === "system" ? "on" : ""} onClick={() => onSave({ sound: { ...s.sound, mode: "system" } })}>All sounds</button>
          </span></div>
        <div className="nx-set"><span className="nx-grow">Fold away after</span>
          <span className="nx-seg">{[15, 60, 300].map((n) => (
            <button key={n} className={s.notch.autoclose_s === n ? "on" : ""} onClick={() => onSave({ notch: { ...s.notch, autoclose_s: n } })}>
              {n < 60 ? `${n}s` : `${n / 60}m`}</button>))}</span></div>
        <div className="nx-set"><span className="nx-grow nx-dim">Wake gesture, voice, personality and avatar</span>
          <button className="nx-btn small" onClick={onOpenSetup}>Open Equalize</button></div>
      </div>
    </div>
  );
}

// ── The three small notches' own views ──────────────────────────────────────

export function TimerView({ timers, now, onAdd, onRemove }: {
  timers: Timer[]; now: number; onAdd: (seconds: number, label: string) => void; onRemove: (id: string) => void;
}) {
  const [custom, setCustom] = useState("");
  const parse = (value: string) => {
    const m = value.trim().toLowerCase().match(/^(\d+(?:\.\d+)?)\s*(h|m|s|min|sec)?$/);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    return m[2]?.startsWith("h") ? n * 3600 : m[2]?.startsWith("s") ? n : n * 60;
  };
  return (
    <div className="nx-card">
      <div className="nx-split">
        <div style={{ minWidth: 150 }}>
          <div className="nx-big-clock">{new Date(now).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
          <div className="nx-sub">{new Date(now).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" })}</div>
        </div>
        <div className="nx-grow" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {timers.map((t) => (
            <div key={t.id} className="nx-item" style={{ padding: "4px 10px" }}>
              <span className="nx-dot" style={{ background: "#34D399" }} />
              <span className="nx-grow nx-ellipsis">{t.label}</span>
              <b className="nx-mono" style={{ fontSize: 13 }}>{formatLeft(t.ends * 1000 - now)}</b>
              <button className="nx-act close" onClick={() => onRemove(t.id)} aria-label="Remove timer">{Icon.close()}</button>
            </div>
          ))}
          <div className="nx-row" style={{ gap: 6, flexWrap: "wrap" }}>
            {[1, 5, 10, 25].map((m) => <button key={m} className="nx-btn small" onClick={() => onAdd(m * 60, `${m} min`)}>{m} min</button>)}
            <input style={{ ...inputStyle, width: 90 }} placeholder="e.g. 45m" value={custom} onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => { const s = parse(custom); if (e.key === "Enter" && s) { onAdd(s, custom); setCustom(""); } }} aria-label="Custom timer" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function formatLeft(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function SoundView({ bars, mode, volume, muted, onMode, onVolume }: {
  bars: number[]; mode: "ai" | "system"; volume: number; muted: boolean; onMode: (m: "ai" | "system") => void; onVolume: (v: number) => void;
}) {
  return (
    <div className="nx-card wash" style={{ ["--wash" as string]: "rgba(165,148,255,.35)" }}>
      <div className="nx-split">
        <div className="nx-meter">{bars.map((b, i) => <i key={i} style={{ height: `${8 + b * 36}px` }} />)}</div>
        <div className="nx-grow" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="nx-title">{mode === "ai" ? "Ichos's voice" : "Everything playing on this PC"}</div>
          <span className="nx-seg">
            <button className={mode === "ai" ? "on" : ""} onClick={() => onMode("ai")}>Ichos's voice</button>
            <button className={mode === "system" ? "on" : ""} onClick={() => onMode("system")}>All sounds</button>
          </span>
          <div className="nx-row" style={{ gap: 10 }}>
            <span className="nx-sub" style={{ width: 70 }}>{muted ? "Muted" : "Effects"}</span>
            <input type="range" min={0} max={100} value={Math.round(volume * 100)} style={{ ["--fill" as string]: `${volume * 100}%`, maxWidth: 200 }}
              onChange={(e) => onVolume(Number(e.target.value) / 100)} aria-label="Effects volume" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AppView({ app, work, onTask, onOpenWork }: {
  app: Pinned; work: Work | null; onTask: (text: string) => void; onOpenWork: () => void;
}) {
  const [text, setText] = useState("");
  const steps = work?.steps ?? [];
  const running = work?.status === "running";
  return (
    <div className="nx-card wash" style={{ ["--wash" as string]: `${app.color}55` }}>
      <div className="nx-split" style={{ alignItems: "stretch", padding: "12px 16px" }}>
        <div style={{ width: 150, display: "flex", flexDirection: "column", gap: 4 }}>
          <MiniIo color={app.color} size={36} state={running ? "working" : "idle"} />
          <div className="nx-title">{app.name}</div>
          <div className="nx-sub nx-ellipsis" title={app.target}>{app.target || app.kind}</div>
        </div>
        <div className="nx-grow" style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <div className="nx-steps" style={{ flex: 1, padding: 0, cursor: steps.length ? "pointer" : "default" }} onClick={steps.length ? onOpenWork : undefined}>
            {steps.length ? steps.slice(-4).map((s, i) => (
              <div key={i} className="nx-step"><span className="k">{s.kind === "note" ? "" : s.kind}</span><span className="nx-ellipsis">{s.title}</span></div>
            )) : <span className="nx-sub">Pinned. Say what to do with {app.name} — e.g. “update this repo”.</span>}
          </div>
          <div className="nx-input" style={{ height: 32 }}>
            <input value={text} placeholder={`Using ${app.name}, …`} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onTask(text.trim()); setText(""); } }} aria-label={`Task using ${app.name}`} />
            <button className="nx-round primary" aria-label="Start" onClick={() => { if (text.trim()) { onTask(text.trim()); setText(""); } }}>{Icon.send()}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
