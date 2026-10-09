/** The blocks added for "super free create" (UPDATE_IDEAS U4): forms, tables, boards, pictures, galleries, action
 * buttons, counters — plus links and stat, which used to render as "not wired yet".
 *
 * Every one draws checked data from dynamic_tabs.py; nothing a tab carries is ever run. What the owner types into a
 * block is kept in this browser (localStorage), like notes and checklists. */

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../api";

type Config = Record<string, unknown>;

function useLocal<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private browsing: not kept */ }
  }, [key, value]);
  return [value, setValue];
}

const muted = { fontSize: 12, color: "var(--color-neutral-500)" } as const;
const input = {
  width: "100%", font: "inherit", fontSize: 13, color: "var(--color-text)", background: "var(--color-surface-2)",
  border: 0, borderRadius: 8, padding: "6px 8px", boxShadow: "inset 0 0 0 1px var(--color-divider)",
} as const;

async function askNyx(prompt: string): Promise<string> {
  const result = await api.post<{ reply: string }>("/api/chat", { message: prompt }, 180000);
  return result.ok ? result.data.reply : result.error;
}

// --- form ---------------------------------------------------------------------------------------------------------

interface Field { name: string; label: string; kind: string; options?: string[]; required?: boolean }

export function FormBlock({ config, storageKey }: { config: Config; storageKey: string }) {
  const fields = (config.fields as Field[]) ?? [];
  const [entries, setEntries] = useLocal<Record<string, unknown>[]>(storageKey, []);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const aiPrompt = String(config.ai_prompt ?? "");

  const submit = async () => {
    const missing = fields.find((f) => f.required && (draft[f.name] === undefined || draft[f.name] === ""));
    if (missing) { setReply(`${missing.label} is needed.`); return; }
    const entry = { ...draft, _at: new Date().toISOString() };
    setEntries((all) => [entry, ...all].slice(0, 200));
    setDraft({});
    if (aiPrompt) {
      setBusy(true);
      setReply(await askNyx(`${aiPrompt}\n\nThe new entry: ${JSON.stringify(entry)}\nEarlier entries (newest first): ${JSON.stringify(entries.slice(0, 20))}`));
      setBusy(false);
    } else setReply("Saved.");
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 8 }}>
      {fields.map((f) => (
        <label key={f.name} style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
          <span>{f.label}{f.required ? " *" : ""}</span>
          {f.kind === "textarea" ? (
            <textarea style={{ ...input, minHeight: 64 }} value={String(draft[f.name] ?? "")} onChange={(e) => setDraft({ ...draft, [f.name]: e.target.value })} />
          ) : f.kind === "select" ? (
            <select style={input} value={String(draft[f.name] ?? "")} onChange={(e) => setDraft({ ...draft, [f.name]: e.target.value })}>
              <option value="">—</option>
              {(f.options ?? []).map((o) => <option key={o}>{o}</option>)}
            </select>
          ) : f.kind === "checkbox" ? (
            <input type="checkbox" checked={Boolean(draft[f.name])} onChange={(e) => setDraft({ ...draft, [f.name]: e.target.checked })} />
          ) : (
            <input style={input} type={f.kind === "number" ? "number" : f.kind === "date" ? "date" : "text"} value={String(draft[f.name] ?? "")}
                   onChange={(e) => setDraft({ ...draft, [f.name]: f.kind === "number" ? Number(e.target.value) : e.target.value })} />
          )}
        </label>
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Nyx is reading…" : String(config.submit ?? "Save")}</button>
        <span style={muted}>{entries.length} saved</span>
      </div>
      {reply && <div style={{ fontSize: 13, whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{reply}</div>}
    </form>
  );
}

// --- table ---------------------------------------------------------------------------------------------------------

export function TableBlock({ config, storageKey }: { config: Config; storageKey: string }) {
  const columns = (config.columns as string[]) ?? [];
  const [rows, setRows] = useLocal<string[][]>(storageKey, (config.rows as string[][]) ?? []);
  const edit = (r: number, c: number, value: string) => setRows((all) => all.map((row, i) => (i === r ? row.map((cell, j) => (j === c ? value : cell)) : row)));
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>{columns.map((c) => <th key={c} style={{ textAlign: "left", padding: "4px 6px", ...muted }}>{c}</th>)}<th /></tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {columns.map((_, c) => (
                <td key={c} style={{ padding: 2 }}>
                  <input style={{ ...input, boxShadow: "none", background: "transparent" }} value={row[c] ?? ""} aria-label={`${columns[c]}, row ${r + 1}`}
                         onChange={(e) => edit(r, c, e.target.value)} />
                </td>
              ))}
              <td><button className="btn" style={{ padding: "1px 6px" }} aria-label={`Remove row ${r + 1}`} onClick={() => setRows((all) => all.filter((_, i) => i !== r))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn btn-secondary" style={{ marginTop: 6 }} onClick={() => setRows((all) => [...all, columns.map(() => "")])}>+ Row</button>
    </div>
  );
}

// --- board ---------------------------------------------------------------------------------------------------------

export function BoardBlock({ config, storageKey }: { config: Config; storageKey: string }) {
  const columns = (config.columns as string[]) ?? [];
  const [cards, setCards] = useLocal<Record<string, string[]>>(storageKey, (config.cards as Record<string, string[]>) ?? {});
  const [adding, setAdding] = useState<Record<string, string>>({});
  const move = (from: number, index: number, to: number) => setCards((all) => {
    const next = { ...all };
    const card = (next[columns[from]] ?? [])[index];
    next[columns[from]] = (next[columns[from]] ?? []).filter((_, i) => i !== index);
    next[columns[to]] = [...(next[columns[to]] ?? []), card];
    return next;
  });
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${columns.length}, minmax(140px, 1fr))`, gap: 8, overflowX: "auto" }}>
      {columns.map((column, c) => (
        <div key={column} style={{ display: "grid", gap: 6, alignContent: "start", padding: 6, borderRadius: 10, background: "var(--color-surface-2)" }}>
          <b style={{ fontSize: 12.5 }}>{column} <span style={muted}>{(cards[column] ?? []).length}</span></b>
          {(cards[column] ?? []).map((card, i) => (
            <div key={`${card}-${i}`} style={{ padding: "6px 8px", borderRadius: 8, background: "var(--color-surface)", fontSize: 13, display: "grid", gap: 4 }}>
              <span>{card}</span>
              <span style={{ display: "flex", gap: 4 }}>
                {c > 0 && <button className="btn" style={{ padding: "0 6px" }} aria-label={`Move ${card} to ${columns[c - 1]}`} onClick={() => move(c, i, c - 1)}>←</button>}
                {c < columns.length - 1 && <button className="btn" style={{ padding: "0 6px" }} aria-label={`Move ${card} to ${columns[c + 1]}`} onClick={() => move(c, i, c + 1)}>→</button>}
                <button className="btn" style={{ padding: "0 6px", marginLeft: "auto" }} aria-label={`Remove ${card}`}
                        onClick={() => setCards((all) => ({ ...all, [column]: (all[column] ?? []).filter((_, j) => j !== i) }))}>×</button>
              </span>
            </div>
          ))}
          <form onSubmit={(e) => { e.preventDefault(); const text = (adding[column] ?? "").trim(); if (!text) return;
            setCards((all) => ({ ...all, [column]: [...(all[column] ?? []), text] })); setAdding({ ...adding, [column]: "" }); }}>
            <input style={input} placeholder="+ Add a card" value={adding[column] ?? ""} onChange={(e) => setAdding({ ...adding, [column]: e.target.value })} aria-label={`Add a card to ${column}`} />
          </form>
        </div>
      ))}
    </div>
  );
}

// --- pictures ------------------------------------------------------------------------------------------------------

export function ImageBlock({ config }: { config: Config }) {
  return (
    <figure style={{ margin: 0, display: "grid", gap: 6 }}>
      <img src={String(config.src ?? "")} alt={String(config.caption ?? "")} loading="lazy" referrerPolicy="no-referrer"
           style={{ width: "100%", maxHeight: 420, objectFit: config.fit === "contain" ? "contain" : "cover", borderRadius: 10 }} />
      {config.caption ? <figcaption style={muted}>{String(config.caption)}</figcaption> : null}
    </figure>
  );
}

export function GalleryBlock({ config }: { config: Config }) {
  const images = (config.images as { src: string; caption: string }[]) ?? [];
  if (!images.length) return <div style={muted}>No pictures yet.</div>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
      {images.map((image) => (
        <a key={image.src} href={image.src} target="_blank" rel="noreferrer" title={image.caption}>
          <img src={image.src} alt={image.caption} loading="lazy" referrerPolicy="no-referrer" style={{ width: "100%", aspectRatio: "1", objectFit: "cover", borderRadius: 8 }} />
        </a>
      ))}
    </div>
  );
}

// --- actions, counter, links, stat ---------------------------------------------------------------------------------

export function ActionsBlock({ config }: { config: Config }) {
  const buttons = (config.buttons as { label: string; do: string; value: string }[]) ?? [];
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState("");
  const run = async (button: { label: string; do: string; value: string }) => {
    if (button.do === "link") { window.open(button.value, "_blank", "noopener"); return; }
    if (button.do === "open_tab") { window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: button.value } })); return; }
    setBusy(button.label);
    setReply(await askNyx(button.value));
    setBusy("");
  };
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {buttons.map((b) => <button key={b.label} className="btn btn-secondary" disabled={!!busy} onClick={() => void run(b)}>{busy === b.label ? "Working…" : b.label}</button>)}
      </div>
      {reply && <div style={{ fontSize: 13, whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{reply}</div>}
    </div>
  );
}

export function CounterBlock({ config, storageKey }: { config: Config; storageKey: string }) {
  const step = Number(config.step ?? 1) || 1;
  const goal = config.goal === null || config.goal === undefined ? null : Number(config.goal);
  const [count, setCount] = useLocal<number>(storageKey, Number(config.start ?? 0));
  const reached = goal !== null && count >= goal;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <button className="btn" aria-label="Down" onClick={() => setCount((n) => n - step)}>−</button>
      <div style={{ textAlign: "center", minWidth: 80 }}>
        <div style={{ fontSize: 30, fontWeight: 700, color: reached ? "var(--color-ok)" : undefined }}>{count}</div>
        <div style={muted}>{String(config.label ?? "")}{goal !== null ? ` · goal ${goal}` : ""}</div>
      </div>
      <button className="btn btn-primary" aria-label="Up" onClick={() => setCount((n) => n + step)}>+</button>
      <button className="btn" style={{ marginLeft: "auto" }} onClick={() => setCount(Number(config.start ?? 0))}>Reset</button>
    </div>
  );
}

export function LinksBlock({ config }: { config: Config }) {
  const links = (config.links as { label: string; url: string }[]) ?? [];
  if (!links.length) return <div style={muted}>No links yet.</div>;
  return (
    <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4, fontSize: 13 }}>
      {links.map((l) => <li key={l.url}><a href={l.url} target="_blank" rel="noreferrer">{l.label || l.url}</a></li>)}
    </ul>
  );
}

export function StatBlock({ config }: { config: Config }) {
  return (
    <div>
      <div style={{ fontSize: 30, fontWeight: 700 }}>{String(config.value ?? "—")}</div>
      {config.label ? <div style={muted}>{String(config.label)}</div> : null}
    </div>
  );
}
