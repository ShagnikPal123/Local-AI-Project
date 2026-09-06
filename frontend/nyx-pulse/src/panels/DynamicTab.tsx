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

import { useEffect, useState } from "react";
import { api } from "../api";
import { PanelShell } from "../components/Panel";

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
          <div style={{ fontSize: 10, color: "var(--color-neutral-700)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
            {edit.source}
            {whenText(edit.at) && ` · ${whenText(edit.at)}`}
          </div>
        </div>
      ))}
    </div>
  );
}

function useLocalValue<T>(key: string, initial: T): [T, (v: T) => void] {
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

function Block({ block, spec }: { block: TabBlock; spec: TabSpec }) {
  const storageKey = `nyx.tab.${spec.id}.${block.type}.${block.title}`;

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
    case "links":
    case "list":
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

  async function apply(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError("");
    const result = await api.post<{ tab: TabSpec; interpreted_by: string }>(
      `/api/tabs/${spec.id}/edit`, { instruction: trimmed },
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setHistory((h) => [{ text: trimmed, by: result.data.interpreted_by }, ...h].slice(0, 6));
    setInstruction("");
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
      </form>

      {error && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 9, lineHeight: 1.5 }}>
          {error}
        </div>
      )}

      <div style={{ marginTop: 14 }}>
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
          <div style={{ fontSize: 10, color: "var(--color-neutral-700)", marginTop: 6, lineHeight: 1.5 }}>
            "local" means it was read without a model call — instant, and works offline.
          </div>
        </div>
      )}
    </aside>
  );
}

export function DynamicTab({ spec, onChanged, onDelete }: {
  spec: TabSpec;
  onChanged: (spec: TabSpec) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
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
