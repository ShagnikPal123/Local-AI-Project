/** Renderer for a user-defined tab spec (ROADMAP CC1, CC8, CC9).
 *
 * The client renders blocks it already knows how to draw. It never evaluates
 * anything from the spec — an unknown block type says so rather than trying, and
 * the accent colour is the only styling a spec can influence.
 *
 * Block content that the user types (notes, checklists) is stored in this
 * browser only. It is per-tab and per-device, which is the honest scope until
 * there is a server-side store for it.
 */

import { useEffect, useRef, useState, type CSSProperties, type Dispatch, type SetStateAction } from "react";
import { api } from "../api";
import { PanelShell } from "../components/Panel";
import { ChartBox } from "../components/chat/ChartBox";
import { TabLook } from "./tabs/TabLook";
import "./tabs/tabs.css";

export interface TabBlock {
  type: string;
  title: string;
  config: Record<string, unknown>;
}

/** One applied change, as the server records it on the tab itself. */
export interface TabEditRecord {
  request: string;
  summary: string;
  at: number;
  source: string;
}

export interface TabSpec {
  id: string;
  label: string;
  icon: string;
  description: string;
  blocks: TabBlock[];
  connectors: string[];
  accent: string;
  source: string;
  /** Newer backends persist the edit trail on the tab; older ones omit it. */
  edits?: TabEditRecord[];
  updated_at?: number;
  /** Declarative appearance settings, validated by the server before storage. */
  background?: Record<string, unknown>;
  theme?: Record<string, unknown>;
}

interface EditOutcome {
  applied: boolean;
  summary: string;
  interpretedBy: string;
  request: string;
}

function whenText(at: number): string {
  if (!at) return "";
  try {
    return new Date(at * 1000).toLocaleString();
  } catch {
    return "";
  }
}

/** The trail of what was asked for and what changed.
 *
 * Rendered in the tab body, not only inside the edit panel, because the
 * complaint was precisely that closing the editor took the evidence with it.
 */
function EditHistory({ edits, compact }: { edits: TabEditRecord[]; compact?: boolean }) {
  if (edits.length === 0) return null;
  // Newest first: the change you just made is the one you are looking for.
  const ordered = [...edits].reverse();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 7 : 9 }}>
      {ordered.map((edit, i) => (
        <div key={`${edit.at}-${i}`} style={{ lineHeight: 1.5 }}>
          <div style={{ fontSize: compact ? 12 : 13, color: "var(--color-text)" }}>
            “{edit.request}”
          </div>
          <div style={{ fontSize: compact ? 11 : 12, color: "var(--color-ok)", marginTop: 2 }}>
            {edit.summary}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-neutral-700)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
            {edit.source}
            {whenText(edit.at) && ` · ${whenText(edit.at)}`}
          </div>
        </div>
      ))}
    </div>
  );
}

function useLocalValue<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private browsing — the content simply will not persist */
    }
  }, [key, value]);
  return [value, setValue];
}

function NotesBlock({ storageKey }: { storageKey: string }) {
  const [text, setText] = useLocalValue(storageKey, "");
  return (
    <>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder="Type here. Saved in this browser."
        style={{
          width: "100%", resize: "vertical", padding: "9px 11px",
          background: "var(--color-nav)", color: "var(--color-text)", border: "none",
          borderRadius: "var(--radius)", boxShadow: "inset 0 0 0 1px var(--color-divider)",
          font: "inherit", fontSize: 13, lineHeight: 1.6,
        }}
      />
      <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 5 }}>
        Stored in this browser only — not synced across devices.
      </div>
    </>
  );
}

interface ChecklistItem { text: string; done: boolean }

function ChecklistBlock({ storageKey }: { storageKey: string }) {
  const [items, setItems] = useLocalValue<ChecklistItem[]>(storageKey, []);
  const [draft, setDraft] = useState("");

  return (
    <>
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginBottom: 8 }}>
          Nothing yet.
        </div>
      )}
      {items.map((item, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
          <input
            type="checkbox"
            checked={item.done}
            onChange={() => setItems(items.map((it, j) =>
              j === i ? { ...it, done: !it.done } : it))}
          />
          <span style={{
            fontSize: 13, flex: 1,
            textDecoration: item.done ? "line-through" : undefined,
            color: item.done ? "var(--color-neutral-600)" : undefined,
          }}>
            {item.text}
          </span>
          <button className="btn" onClick={() => setItems(items.filter((_, j) => j !== i))}
            style={{ fontSize: 11, color: "var(--color-neutral-700)", padding: 0 }}>
            ×
          </button>
        </div>
      ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.trim()) return;
          setItems([...items, { text: draft.trim(), done: false }]);
          setDraft("");
        }}
        style={{ marginTop: 8 }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add an item…"
          style={{
            width: "100%", padding: "7px 9px", background: "var(--color-nav)",
            color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
            boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
          }}
        />
      </form>
    </>
  );
}

function ScopedChatBlock({ tabLabel }: { tabLabel: string }) {
  const [messages, setMessages] = useState<{ role: string; text: string }[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    const result = await api.post<{ reply: string }>("/api/chat", {
      message: `[In the context of my "${tabLabel}" tab] ${text}`,
    });
    setBusy(false);
    setMessages((m) => [...m, {
      role: result.ok ? "assistant" : "error",
      text: result.ok ? result.data.reply : result.error,
    }]);
  }

  return (
    <>
      <div style={{ maxHeight: 220, overflowY: "auto", marginBottom: 8 }}>
        {messages.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)" }}>
            Ask something. The agent is told this is your {tabLabel} tab.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{
            fontSize: 13, padding: "5px 0", lineHeight: 1.55, whiteSpace: "pre-wrap",
            color: m.role === "user" ? "var(--color-text)"
              : m.role === "error" ? "var(--color-danger)" : "var(--color-neutral-400)",
          }}>
            {m.role === "user" ? "› " : ""}{m.text}
          </div>
        ))}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={busy ? "Thinking…" : "Ask…"}
          disabled={busy}
          style={{
            width: "100%", padding: "7px 9px", background: "var(--color-nav)",
            color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
            boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
          }}
        />
      </form>
    </>
  );
}

const fieldStyle: CSSProperties = {
  width: "100%", padding: "7px 9px", background: "var(--color-nav)",
  color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
  boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
};

function configText(config: Record<string, unknown>, key: string, fallback = ""): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function configNumber(config: Record<string, unknown>, key: string, fallback = 0): number {
  const value = Number(config[key]);
  return Number.isFinite(value) ? value : fallback;
}

function formatDuration(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

/** A list from a tab spec, deliberately rendered as text rather than a connector call.
 * A tab may name an allowed connector, but it can never silently perform a search. */
function ListBlock({ config }: { config: Record<string, unknown> }) {
  const items = Array.isArray(config.items) ? config.items.map(String).filter(Boolean) : [];
  if (items.length === 0) {
    return <div style={{ fontSize: 12, color: "var(--color-neutral-600)" }}>No items have been added yet.</div>;
  }
  return (
    <ul style={{ margin: 0, paddingLeft: 19, display: "grid", gap: 5, fontSize: 13, lineHeight: 1.5 }}>
      {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
    </ul>
  );
}

interface TrackerEntry { value: number | boolean; at: number }

function TrackerBlock({ config, storageKey }: { config: Record<string, unknown>; storageKey: string }) {
  const yesNo = config.kind === "yes_no";
  const goal = config.goal === null || config.goal === undefined ? null : configNumber(config, "goal");
  const unit = configText(config, "unit");
  const [entries, setEntries] = useLocalValue<TrackerEntry[]>(storageKey, []);
  const [draft, setDraft] = useState("");
  const total = yesNo
    ? entries.filter((entry) => entry.value === true).length
    : entries.reduce((sum, entry) => sum + (typeof entry.value === "number" ? entry.value : 0), 0);
  const progress = goal && goal > 0 ? Math.min(100, Math.max(0, (total / goal) * 100)) : null;

  function add(value: number | boolean) {
    setEntries((current) => [...current, { value, at: Date.now() }].slice(-100));
    setDraft("");
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <strong style={{ fontSize: 21, fontFamily: "var(--font-mono)", fontWeight: 500 }}>{total}{unit && ` ${unit}`}</strong>
        {goal !== null && <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>of {goal}{unit && ` ${unit}`}</span>}
      </div>
      {progress !== null && (
        <div aria-label={`${Math.round(progress)}% of goal`} style={{ height: 5, borderRadius: 4, overflow: "hidden", background: "var(--color-divider)", marginBottom: 10 }}>
          <div style={{ height: "100%", width: `${progress}%`, borderRadius: 4, background: "var(--color-accent)" }} />
        </div>
      )}
      {yesNo ? (
        <button className="btn btn-secondary" onClick={() => add(true)}>Mark done</button>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); const value = Number(draft); if (Number.isFinite(value)) add(value); }} style={{ display: "flex", gap: 7 }}>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} inputMode="decimal" placeholder={`Add ${unit || "value"}`} style={{ ...fieldStyle, minWidth: 0 }} />
          <button className="btn btn-secondary" type="submit" disabled={!draft.trim()}>Add</button>
        </form>
      )}
      {entries.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--color-neutral-600)", lineHeight: 1.7 }}>
          Latest: {[...entries].slice(-4).reverse().map((entry) => `${entry.value === true ? "done" : entry.value}${unit && typeof entry.value === "number" ? ` ${unit}` : ""}`).join(" · ")}
          <button className="btn" onClick={() => setEntries([])} style={{ marginLeft: 8, padding: 0, fontSize: 11, color: "var(--color-neutral-600)" }}>clear</button>
        </div>
      )}
    </div>
  );
}

interface TimerState { seconds: number; running: boolean; lastTick: number; finished: boolean }

function AskNyx({ prompt, label = "Ask Nyx" }: { prompt: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");
  async function run() {
    if (!prompt || busy) return;
    setBusy(true);
    const result = await api.post<{ reply: string }>("/api/chat", { message: prompt });
    setBusy(false);
    setReply(result.ok ? result.data.reply : result.error);
  }
  return (
    <div style={{ marginTop: 9 }}>
      <button className="btn btn-secondary" onClick={() => void run()} disabled={!prompt || busy}>{busy ? "Nyx is working…" : label}</button>
      {!prompt && <span style={{ marginLeft: 8, fontSize: 11, color: "var(--color-neutral-600)" }}>Add an AI prompt when creating this block.</span>}
      {reply && <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--color-divider)", fontSize: 12, whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{reply}</div>}
    </div>
  );
}

function TimerBlock({ config, storageKey }: { config: Record<string, unknown>; storageKey: string }) {
  const mode = configText(config, "mode", "countdown");
  const isCountDown = mode !== "stopwatch";
  const initial = Math.max(60, Math.round(configNumber(config, "minutes", 25) * 60));
  const [timer, setTimer] = useLocalValue<TimerState>(storageKey, { seconds: isCountDown ? initial : 0, running: false, lastTick: 0, finished: false });
  const aiPrompt = configText(config, "ai_prompt");

  useEffect(() => {
    if (!timer.running) return;
    const interval = window.setInterval(() => {
      setTimer((current) => {
        const now = Date.now();
        const elapsed = Math.max(1, Math.floor((now - current.lastTick) / 1000));
        if (!current.lastTick) return { ...current, lastTick: now };
        if (!isCountDown) return { ...current, seconds: current.seconds + elapsed, lastTick: now };
        const seconds = Math.max(0, current.seconds - elapsed);
        return { ...current, seconds, lastTick: now, running: seconds > 0, finished: seconds === 0 };
      });
    }, 500);
    return () => window.clearInterval(interval);
  }, [isCountDown, setTimer, timer.running]);

  function reset() {
    setTimer({ seconds: isCountDown ? initial : 0, running: false, lastTick: 0, finished: false });
  }

  return (
    <div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 34, letterSpacing: "-0.04em", fontVariantNumeric: "tabular-nums" }}>{formatDuration(timer.seconds)}</div>
      <div style={{ display: "flex", gap: 7, marginTop: 8 }}>
        <button className="btn btn-secondary" onClick={() => setTimer((current) => ({ ...current, running: !current.running, lastTick: Date.now(), finished: false }))}>
          {timer.running ? "Pause" : "Start"}
        </button>
        <button className="btn" onClick={reset} style={{ color: "var(--color-neutral-500)" }}>Reset</button>
        <span style={{ alignSelf: "center", fontSize: 11, color: "var(--color-neutral-600)", textTransform: "capitalize" }}>{mode}</span>
      </div>
      {timer.finished && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--color-ok)" }}>
          Timer complete.{aiPrompt && <AskNyx prompt={aiPrompt} label="Give Nyx the next step" />}
        </div>
      )}
    </div>
  );
}

function AiTaskBlock({ config }: { config: Record<string, unknown> }) {
  const prompt = configText(config, "prompt");
  const everyMinutes = Math.max(0, Math.floor(configNumber(config, "every_minutes")));
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");
  const [ready, setReady] = useState(false);

  async function run() {
    if (!prompt || busy) return;
    setBusy(true);
    const result = await api.post<{ reply: string }>("/api/chat", { message: prompt });
    setBusy(false);
    setReply(result.ok ? result.data.reply : result.error);
    setReady(false);
  }

  useEffect(() => {
    if (everyMinutes < 5 || !prompt) return;
    // A cadence makes the task ready; it never spends a user's model budget on
    // its own. The owner still chooses when the request is actually sent.
    const interval = window.setInterval(() => setReady(true), everyMinutes * 60_000);
    return () => window.clearInterval(interval);
  }, [everyMinutes, prompt]);

  return (
    <div>
      <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--color-neutral-400)" }}>{prompt || "Add a prompt to tell Nyx what this action should do."}</div>
      {everyMinutes >= 5 && <div style={{ fontSize: 11, color: ready ? "var(--color-ok)" : "var(--color-neutral-600)", marginTop: 6 }}>{ready ? "Ready for your review." : `Ready every ${everyMinutes} minutes while this tab is open.`}</div>}
      <button className="btn btn-secondary" onClick={() => void run()} disabled={!prompt || busy} style={{ marginTop: 9 }}>{busy ? "Nyx is working…" : ready ? "Run scheduled action" : "Run now"}</button>
      {reply && <div style={{ marginTop: 9, paddingTop: 9, borderTop: "1px solid var(--color-divider)", whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.55 }}>{reply}</div>}
    </div>
  );
}

type Mark = "X" | "O" | null;
const TTT_LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];
function ticWinner(cells: Mark[]): Mark | "draw" | null {
  for (const [a, b, c] of TTT_LINES) if (cells[a] && cells[a] === cells[b] && cells[a] === cells[c]) return cells[a];
  return cells.every(Boolean) ? "draw" : null;
}
function ticMove(cells: Mark[], mark: Exclude<Mark, null>): number {
  const other: Exclude<Mark, null> = mark === "X" ? "O" : "X";
  for (const candidate of [mark, other] as Array<Exclude<Mark, null>>) {
    for (let index = 0; index < cells.length; index += 1) if (!cells[index]) {
      const next = [...cells]; next[index] = candidate;
      if (ticWinner(next) === candidate) return index;
    }
  }
  return [4, 0, 2, 6, 8, 1, 3, 5, 7].find((index) => !cells[index]) ?? -1;
}

function TicTacToe({ versusNyx = false }: { versusNyx?: boolean }) {
  const [cells, setCells] = useState<Mark[]>(Array(9).fill(null));
  const [thinking, setThinking] = useState(false);
  const winner = ticWinner(cells);

  useEffect(() => {
    if (!versusNyx || !thinking || winner) return;
    const timeout = window.setTimeout(() => {
      setCells((current) => {
        const move = ticMove(current, "O");
        return move < 0 ? current : current.map((cell, index) => index === move ? "O" : cell);
      });
      setThinking(false);
    }, 280);
    return () => window.clearTimeout(timeout);
  }, [cells, thinking, versusNyx, winner]);

  function move(index: number) {
    if (cells[index] || winner || thinking) return;
    setCells((current) => current.map((cell, at) => at === index ? "X" : cell));
    if (versusNyx) setThinking(true);
  }
  const status = winner === "draw" ? "Draw." : winner ? `${winner === "X" ? "You" : "Nyx"} won.` : thinking ? "Nyx is choosing…" : versusNyx ? "Your turn — X" : "X starts.";
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 42px)", gap: 4 }}>
        {cells.map((cell, index) => <button key={index} onClick={() => move(index)} aria-label={`cell ${index + 1}${cell ? `, ${cell}` : ""}`} style={{ width: 42, height: 42, borderRadius: 8, background: "var(--color-nav)", color: cell === "X" ? "var(--color-accent)" : "var(--color-ok)", fontSize: 18, fontWeight: 700 }}>{cell}</button>)}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontSize: 12, color: "var(--color-neutral-500)" }}>
        <span>{status}</span><button className="btn" onClick={() => { setCells(Array(9).fill(null)); setThinking(false); }} style={{ padding: 0, fontSize: 11, color: "var(--color-neutral-600)" }}>new game</button>
      </div>
    </div>
  );
}

function ConnectFour() {
  const empty = () => Array.from({ length: 6 }, () => Array<Mark>(7).fill(null));
  const [grid, setGrid] = useState<Mark[][]>(empty);
  const [thinking, setThinking] = useState(false);
  const winner = connectWinner(grid);

  useEffect(() => {
    if (!thinking || winner) return;
    const timeout = window.setTimeout(() => {
      setGrid((current) => connectDrop(current, connectMove(current, "O"), "O"));
      setThinking(false);
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [grid, thinking, winner]);

  function drop(column: number) {
    if (thinking || winner || grid[0][column]) return;
    setGrid((current) => connectDrop(current, column, "X"));
    setThinking(true);
  }
  const status = winner === "draw" ? "Draw." : winner ? `${winner === "X" ? "You" : "Nyx"} won.` : thinking ? "Nyx is choosing…" : "Your turn — red.";
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 27px)", gap: 3, padding: 5, width: "fit-content", background: "#273b84", borderRadius: 9 }}>
        {grid.flatMap((row, rowIndex) => row.map((cell, column) => <button key={`${rowIndex}-${column}`} onClick={() => drop(column)} aria-label={`column ${column + 1}`} style={{ width: 27, height: 27, padding: 0, borderRadius: "50%", background: cell === "X" ? "#ea6d67" : cell === "O" ? "#f3d15f" : "#e9eef8", border: 0 }} />))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontSize: 12, color: "var(--color-neutral-500)" }}><span>{status}</span><button className="btn" onClick={() => { setGrid(empty()); setThinking(false); }} style={{ padding: 0, fontSize: 11, color: "var(--color-neutral-600)" }}>new game</button></div>
    </div>
  );
}

function connectDrop(grid: Mark[][], column: number, mark: Exclude<Mark, null>): Mark[][] {
  if (column < 0 || grid[0][column]) return grid;
  const next = grid.map((row) => [...row]);
  for (let row = next.length - 1; row >= 0; row -= 1) if (!next[row][column]) { next[row][column] = mark; break; }
  return next;
}
function connectWinner(grid: Mark[][]): Mark | "draw" | null {
  const directions = [[1, 0], [0, 1], [1, 1], [1, -1]];
  for (let row = 0; row < 6; row += 1) for (let column = 0; column < 7; column += 1) {
    const mark = grid[row][column];
    if (!mark) continue;
    if (directions.some(([dy, dx]) => [1, 2, 3].every((step) => grid[row + dy * step]?.[column + dx * step] === mark))) return mark;
  }
  return grid.every((row) => row.every(Boolean)) ? "draw" : null;
}
function connectMove(grid: Mark[][], mark: Exclude<Mark, null>): number {
  const available = [3, 2, 4, 1, 5, 0, 6].filter((column) => !grid[0][column]);
  const other: Exclude<Mark, null> = mark === "X" ? "O" : "X";
  for (const candidate of [mark, other] as Array<Exclude<Mark, null>>) {
    const winning = available.find((column) => connectWinner(connectDrop(grid, column, candidate)) === candidate);
    if (winning !== undefined) return winning;
  }
  return available[0] ?? -1;
}

function MemoryGame() {
  const fresh = () => [...["●", "■", "▲", "◆", "★", "✦"], ...["●", "■", "▲", "◆", "★", "✦"]].sort(() => Math.random() - 0.5);
  const [cards, setCards] = useState(fresh);
  const [flipped, setFlipped] = useState<number[]>([]);
  const [matched, setMatched] = useState<number[]>([]);
  function reveal(index: number) {
    if (flipped.length >= 2 || flipped.includes(index) || matched.includes(index)) return;
    const next = [...flipped, index];
    setFlipped(next);
    if (next.length === 2) {
      const pair = cards[next[0]] === cards[next[1]];
      window.setTimeout(() => { if (pair) setMatched((current) => [...current, ...next]); setFlipped([]); }, 520);
    }
  }
  const complete = matched.length === cards.length;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 39px)", gap: 5 }}>
        {cards.map((card, index) => {
          const visible = flipped.includes(index) || matched.includes(index);
          return <button key={index} onClick={() => reveal(index)} aria-label={visible ? card : "hidden card"} style={{ width: 39, height: 39, padding: 0, borderRadius: 8, background: visible ? "var(--color-nav)" : "var(--color-accent)", color: "var(--color-text)", fontSize: 16 }}>{visible ? card : "?"}</button>;
        })}
      </div>
      <div style={{ display: "flex", gap: 9, marginTop: 8, fontSize: 12, color: "var(--color-neutral-500)" }}><span>{complete ? "You found every pair." : `${matched.length / 2} of ${cards.length / 2} pairs`}</span><button className="btn" onClick={() => { setCards(fresh()); setFlipped([]); setMatched([]); }} style={{ padding: 0, fontSize: 11, color: "var(--color-neutral-600)" }}>new game</button></div>
    </div>
  );
}

type Point = [number, number];
function SnakeGame() {
  const size = 12;
  const initial = { snake: [[5, 6], [4, 6]] as Point[], food: [9, 6] as Point, dead: false };
  const [state, setState] = useState(initial);
  const [playing, setPlaying] = useState(false);
  const direction = useRef<Point>([1, 0]);
  function change(next: Point) {
    const current = direction.current;
    if (next[0] === -current[0] && next[1] === -current[1]) return;
    direction.current = next;
  }
  useEffect(() => {
    if (!playing || state.dead) return;
    const interval = window.setInterval(() => setState((current) => {
      const head = current.snake[0];
      const next: Point = [head[0] + direction.current[0], head[1] + direction.current[1]];
      if (next[0] < 0 || next[1] < 0 || next[0] >= size || next[1] >= size || current.snake.some(([x, y]) => x === next[0] && y === next[1])) return { ...current, dead: true };
      const ate = next[0] === current.food[0] && next[1] === current.food[1];
      const snake = [next, ...current.snake];
      if (!ate) snake.pop();
      let food = current.food;
      if (ate) {
        const open: Point[] = [];
        for (let y = 0; y < size; y += 1) for (let x = 0; x < size; x += 1) if (!snake.some(([sx, sy]) => sx === x && sy === y)) open.push([x, y]);
        food = open[Math.floor(Math.random() * open.length)] ?? current.food;
      }
      return { snake, food, dead: false };
    }), 180);
    return () => window.clearInterval(interval);
  }, [playing, state.dead]);
  function reset() { direction.current = [1, 0]; setState(initial); setPlaying(false); }
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${size}, 12px)`, gap: 1, width: "fit-content", padding: 4, background: "#0b1513", borderRadius: 8 }}>
        {Array.from({ length: size * size }, (_, index) => {
          const x = index % size, y = Math.floor(index / size);
          const snake = state.snake.some(([sx, sy]) => sx === x && sy === y);
          const food = state.food[0] === x && state.food[1] === y;
          return <span key={index} style={{ width: 12, height: 12, borderRadius: 3, background: snake ? "#78d9a0" : food ? "#f29177" : "#14251f" }} />;
        })}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
        <button className="btn btn-secondary" onClick={() => setPlaying((value) => !value)} disabled={state.dead}>{playing ? "Pause" : "Play"}</button>
        {([ [0, -1, "↑"], [-1, 0, "←"], [0, 1, "↓"], [1, 0, "→"] ] as Array<[number, number, string]>).map(([x, y, label]) => <button className="btn" key={label} onClick={() => change([x, y])} style={{ padding: "2px 7px" }}>{label}</button>)}
        <button className="btn" onClick={reset} style={{ padding: "2px 7px", color: "var(--color-neutral-600)" }}>{state.dead ? "Try again" : "Reset"}</button>
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: state.dead ? "var(--color-danger)" : "var(--color-neutral-600)" }}>{state.dead ? `Game over · score ${state.snake.length - 2}` : `Score ${state.snake.length - 2}`}</div>
    </div>
  );
}

function Block({ block, spec }: { block: TabBlock; spec: TabSpec }) {
  const storageKey = `nyx.tab.${spec.id}.${block.type}.${block.title}`;
  const theme = spec.theme ?? {};
  const surface = theme.surface === "glass" ? "rgba(18, 18, 24, 0.72)"
    : theme.surface === "clear" ? "transparent" : "var(--color-surface)";
  const font = theme.font === "rounded" ? "ui-rounded, system-ui, sans-serif"
    : theme.font === "serif" ? "Georgia, serif"
    : theme.font === "mono" ? "var(--font-mono)" : undefined;

  let body: React.ReactNode;
  switch (block.type) {
    case "notes":
      body = <NotesBlock storageKey={storageKey} />;
      break;
    case "checklist":
      body = <ChecklistBlock storageKey={storageKey} />;
      break;
    case "chat":
      body = <ScopedChatBlock tabLabel={spec.label} />;
      break;
    case "text":
      body = (
        <div style={{ fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
          {String(block.config.text ?? block.title ?? "")}
        </div>
      );
      break;
    case "list":
      body = <ListBlock config={block.config} />;
      break;
    case "chart":
      body = <ChartBox source={JSON.stringify(block.config.chart ?? {})} />;
      break;
    case "tracker":
      body = <TrackerBlock config={block.config} storageKey={storageKey} />;
      break;
    case "timer":
      body = <TimerBlock config={block.config} storageKey={storageKey} />;
      break;
    case "ai_task":
      body = <AiTaskBlock config={block.config} />;
      break;
    case "competition":
      body = block.config.game === "connect4" ? <ConnectFour /> : <TicTacToe versusNyx />;
      break;
    case "game":
      body = block.config.game === "memory" ? <MemoryGame />
        : block.config.game === "tictactoe" ? <TicTacToe versusNyx /> : <SnakeGame />;
      break;
    case "links":
    case "stat":
    case "embed":
      body = (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          The <strong>{block.type}</strong> block is defined but not wired to a data source
          yet. It is shown so the layout is honest about what the tab contains.
        </div>
      );
      break;
    default:
      // A spec can only name known types, but a client older than the spec is
      // possible — say so rather than rendering an empty box.
      body = (
        <div style={{ fontSize: 12, color: "var(--color-warn)" }}>
          This block type ({block.type}) is not supported by this version of the app.
        </div>
      );
  }

  return (
    <div className="card" style={{
      borderLeft: spec.accent ? `3px solid ${spec.accent}` : undefined,
      background: surface,
      backdropFilter: theme.surface === "glass" ? "blur(12px)" : undefined,
      color: typeof theme.text === "string" ? theme.text : undefined,
      borderRadius: typeof theme.radius === "number" ? theme.radius : undefined,
      fontFamily: font,
    }}>
      {block.title && (
        <div className="label" style={{ marginBottom: 9 }}>{block.title}</div>
      )}
      {body}
    </div>
  );
}


/** Side edit panel (CC8).
 *
 * Sits on the edge of the tab it edits, so a change and its result are visible
 * at once. Typed instructions go to the conversational endpoint; the reply says
 * whether it was read locally or needed the model, because "instant and free"
 * versus "a round trip" is a difference worth seeing.
 */
function EditPanel({ spec, onChanged, onClose }: {
  spec: TabSpec;
  onChanged: (spec: TabSpec) => void;
  onClose: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<{ text: string; by: string }[]>([]);

  const [outcome, setOutcome] = useState<string>("");

  async function apply(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError("");
    setOutcome("");
    const result = await api.post<{
      tab: TabSpec;
      interpreted_by: string;
      applied?: boolean;
      summary?: string;
    }>(`/api/tabs/${spec.id}/edit`, { instruction: trimmed });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }

    setHistory((h) => [{ text: trimmed, by: result.data.interpreted_by }, ...h].slice(0, 6));
    // The instruction deliberately stays in the box. Clearing it on success was
    // the reported complaint: with the text gone and the change sometimes subtle,
    // there was no way to tell whether it had worked, been ignored, or still been
    // running. Leaving it there means you can read what you asked, see the result
    // beside it, and tweak the wording without retyping.
    setOutcome(
      result.data.summary ||
        (result.data.applied === false ? "Nothing changed." : "Applied."),
    );
    onChanged(result.data.tab);
  }

  const suggestions = ["make it green", "add a checklist", "rename it to Journal"];

  return (
    <aside style={{
      width: 264, flex: "none", padding: "14px 16px", overflowY: "auto",
      background: "var(--color-nav)", boxShadow: "inset 1px 0 0 var(--color-divider)",
    }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <span className="label">Edit this tab</span>
        <button className="btn" onClick={onClose}
          style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-600)", padding: 0 }}>
          close
        </button>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); void apply(instruction); }}>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          disabled={busy}
          placeholder="Say what to change…"
          style={{
            width: "100%", resize: "vertical", padding: "8px 10px",
            background: "var(--color-surface)", color: "var(--color-text)", border: "none",
            borderRadius: "var(--radius)", boxShadow: "inset 0 0 0 1px var(--color-divider)",
            font: "inherit", fontSize: 13, marginBottom: 8,
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !instruction.trim()}
          style={{ width: "100%", justifyContent: "center", opacity: busy || !instruction.trim() ? 0.5 : 1 }}>
          {busy ? "Applying…" : "Apply"}
        </button>

        {busy && (
          <div style={{ marginTop: 8 }} aria-live="polite">
            <div className="nyx-progress"><span /></div>
            <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 5, lineHeight: 1.5 }}>
              Simple changes apply instantly. Anything with a title, a list of items, or
              several parts is sent to the model, which takes a few seconds.
            </div>
          </div>
        )}

        {!busy && outcome && (
          <div style={{
            marginTop: 8, fontSize: 12, lineHeight: 1.5,
            color: outcome === "Nothing changed."
              ? "var(--color-warn)" : "var(--color-ok)",
          }} aria-live="polite">
            {outcome === "Nothing changed."
              ? "Nothing changed — the tab already looked like that. Try being more specific."
              : `Done: ${outcome}`}
          </div>
        )}
      </form>

      {error && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 9, lineHeight: 1.5 }}>
          {error}
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <TabLook spec={spec} onChanged={onChanged} />
        <div className="label" style={{ marginBottom: 6 }}>Try</div>
        {suggestions.map((s) => (
          <button key={s} onClick={() => void apply(s)} disabled={busy}
            style={{
              display: "block", width: "100%", textAlign: "left", padding: "5px 8px",
              marginBottom: 4, borderRadius: 6, fontSize: 12,
              background: "var(--color-surface)", color: "var(--color-neutral-400)",
            }}>
            {s}
          </button>
        ))}
      </div>

      {history.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="label" style={{ marginBottom: 6 }}>Applied</div>
          {history.map((h, i) => (
            <div key={i} style={{ fontSize: 11, color: "var(--color-neutral-600)", padding: "2px 0" }}>
              {h.text}
              <span style={{ color: h.by === "local" ? "var(--color-ok)" : "var(--color-accent)" }}>
                {" "}· {h.by}
              </span>
            </div>
          ))}
          <div style={{ fontSize: 11, color: "var(--color-neutral-700)", marginTop: 6, lineHeight: 1.5 }}>
            "local" means it was read without a model call — instant, and works offline.
          </div>
        </div>
      )}
    </aside>
  );
}

function backdropStyle(background: Record<string, unknown> | undefined): CSSProperties {
  const value = background ?? {};
  const kind = value.kind;
  if (kind === "color" && typeof value.value === "string" && /^#[0-9a-f]{6}$/i.test(value.value)) {
    return { backgroundColor: value.value };
  }
  if (kind === "gradient" && Array.isArray(value.colors)) {
    const colors = value.colors.filter((color): color is string => typeof color === "string" && /^#[0-9a-f]{6}$/i.test(color)).slice(0, 3);
    const angle = Math.max(0, Math.min(360, Number(value.angle) || 135));
    if (colors.length >= 2) return { backgroundImage: `linear-gradient(${angle}deg, ${colors.join(", ")})` };
  }
  if (kind === "image" && typeof value.value === "string" && (/^https:\/\/[^\s"'<>()]{4,500}$/.test(value.value) || /^\/api\/uploads\/[A-Za-z0-9_-]{4,64}$/.test(value.value))) {
    const dim = Math.max(0, Math.min(0.9, Number(value.dim) || 0.35));
    const blur = Math.max(0, Math.min(20, Number(value.blur) || 0));
    return {
      backgroundImage: `linear-gradient(rgba(9, 10, 15, ${dim}), rgba(9, 10, 15, ${dim})), url("${value.value}")`,
      backgroundSize: "cover", backgroundPosition: "center", backgroundAttachment: "fixed",
      // A CSS blur would blur the controls too. The soft overlay retains text clarity instead.
      boxShadow: blur ? `inset 0 0 ${blur * 2}px rgba(9, 10, 15, 0.75)` : undefined,
    };
  }
  return {};
}

export function DynamicTab({ spec, onChanged, onDelete }: {
  spec: TabSpec;
  onChanged: (spec: TabSpec) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const background = backdropStyle(spec.background);

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0, ...background }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PanelShell
          title={spec.label}
          subtitle={spec.description || `${spec.blocks.length} blocks · your tab`}
          actions={
            <>
              <button className="btn btn-secondary" onClick={() => setEditing((v) => !v)}>
                {editing ? "Done" : "Edit"}
              </button>
              <button className="btn btn-secondary" onClick={onDelete}
                style={{ color: "var(--color-danger)" }}>Delete</button>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {spec.connectors.length > 0 && (
              <div style={{ fontSize: 11, color: "var(--color-neutral-600)" }}>
                Uses: {spec.connectors.join(", ")}
              </div>
            )}
            {spec.blocks.map((block, i) => (
              <Block key={i} block={block} spec={spec} />
            ))}
          </div>
        </PanelShell>
      </div>

      {editing && (
        <EditPanel
          spec={spec}
          onChanged={onChanged}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}
