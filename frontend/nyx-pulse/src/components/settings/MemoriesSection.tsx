/** Settings › Sessions & memory › Saved memories: the lasting memory list, like Claude's memory files.
 *
 * The owner (2026-10-15): "Similar to how claude can add things to its files by id the fact it was added and wanted for
 * long use, I would like a similar feature." Each memory shows its id, the day it was added, and whether it is marked
 * to keep long term (with why). Everything is editable here; the chat saves new ones when told "remember this".
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";

export interface SavedMemory {
  id: string;
  topic: string;
  content: string;
  source?: string;
  added_at?: string | null;
  updated_at?: string | null;
  keep?: boolean;
  keep_reason?: string;
}

interface Draft { topic: string; content: string; keep: boolean; keep_reason: string }

const EMPTY: Draft = { topic: "", content: "", keep: false, keep_reason: "" };

function day(iso?: string | null): string {
  if (!iso) return "before dates were kept";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function sourceLabel(source?: string): string {
  if (!source || source === "user") return "you";
  if (source === "chat") return "a chat";
  if (source.startsWith("chat:")) return "a deleted chat";
  return source;
}

function MemoryForm({ initial, busy, onSave, onCancel }: {
  initial: Draft;
  busy: boolean;
  onSave: (draft: Draft) => void;
  onCancel?: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const ready = draft.topic.trim() !== "" && draft.content.trim() !== "";
  return (
    <form className="memories__form" onSubmit={(e) => { e.preventDefault(); if (ready) onSave(draft); }}>
      <input className="text-input" value={draft.topic} placeholder="Topic, e.g. favourite editor" aria-label="Topic"
        onChange={(e) => setDraft({ ...draft, topic: e.target.value })} />
      <textarea className="text-input" rows={2} value={draft.content} placeholder="What to remember" aria-label="What to remember"
        onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
      <label className="memories__keep">
        <input type="checkbox" checked={draft.keep} onChange={(e) => setDraft({ ...draft, keep: e.target.checked })} />
        Keep long term
      </label>
      {draft.keep && (
        <input className="text-input" value={draft.keep_reason} placeholder="Why keep it? (optional)" aria-label="Why keep it"
          onChange={(e) => setDraft({ ...draft, keep_reason: e.target.value })} />
      )}
      <div className="memories__actions">
        <button type="submit" className="btn" disabled={!ready || busy}>{busy ? "Saving…" : "Save"}</button>
        {onCancel && <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}

export function MemoriesSection({ initial }: { initial: SavedMemory[] }) {
  const [items, setItems] = useState<SavedMemory[]>(initial);
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState<"all" | "keep">("all");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const reload = useCallback(async () => {
    const result = await api.get<{ important?: SavedMemory[] }>("/api/memory");
    if (result.ok) setItems(result.data.important ?? []);
  }, []);
  useEffect(() => { setItems(initial); }, [initial]);

  const shown = useMemo(() => {
    const list = filter === "keep" ? items.filter((m) => m.keep) : items;
    // Kept memories first, then newest first.
    return [...list].sort((a, b) => Number(!!b.keep) - Number(!!a.keep) || String(b.added_at ?? "").localeCompare(String(a.added_at ?? "")));
  }, [items, filter]);

  async function add(draft: Draft) {
    setBusy(true);
    const result = await api.post<{ memory: SavedMemory }>("/api/memory/important", draft);
    setBusy(false);
    if (!result.ok) { setNote(result.error); return; }
    setAdding(false);
    setNote(`Saved as ${result.data.memory.id}.`);
    void reload();
  }

  async function save(id: string, draft: Draft) {
    setBusy(true);
    const result = await api.patch<{ memory: SavedMemory }>(`/api/memory/important/${encodeURIComponent(id)}`, draft);
    setBusy(false);
    if (!result.ok) { setNote(result.error); return; }
    setEditing(null);
    setNote("");
    setItems((list) => list.map((m) => (m.id === id ? result.data.memory : m)));
  }

  async function toggleKeep(memory: SavedMemory) {
    const result = await api.patch<{ memory: SavedMemory }>(`/api/memory/important/${encodeURIComponent(memory.id)}`, { keep: !memory.keep });
    if (result.ok) setItems((list) => list.map((m) => (m.id === memory.id ? result.data.memory : m)));
  }

  async function remove(memory: SavedMemory) {
    if (!window.confirm(`Forget "${memory.topic}"?`)) return;
    const result = await api.del<{ removed: boolean }>(`/api/memory/important/${encodeURIComponent(memory.id)}`);
    if (result.ok) setItems((list) => list.filter((m) => m.id !== memory.id));
    else setNote(result.error);
  }

  const keptCount = items.filter((m) => m.keep).length;
  return (
    <div className="memories">
      <div className="memories__bar">
        <div className="platform-seg" role="tablist" aria-label="Which memories">
          <button type="button" role="tab" aria-selected={filter === "all"} className={filter === "all" ? "is-on" : ""}
            onClick={() => setFilter("all")}>All {items.length}</button>
          <button type="button" role="tab" aria-selected={filter === "keep"} className={filter === "keep" ? "is-on" : ""}
            onClick={() => setFilter("keep")}>Kept long term {keptCount}</button>
        </div>
        {!adding && <button type="button" className="btn" onClick={() => { setAdding(true); setEditing(null); }}>Add memory</button>}
      </div>
      {note && <div className="memories__note" role="status">{note}</div>}
      {adding && <MemoryForm initial={EMPTY} busy={busy} onSave={(d) => void add(d)} onCancel={() => setAdding(false)} />}
      {shown.length === 0 && !adding && (
        <div className="memories__empty">
          {filter === "keep" ? "Nothing is marked to keep long term yet." : "No saved memories yet. Say “remember this” in a chat, or add one here."}
        </div>
      )}
      <ul className="memories__list">
        {shown.map((memory) => (
          <li key={memory.id} className={`memories__item${memory.keep ? " memories__item--kept" : ""}`}>
            {editing === memory.id ? (
              <MemoryForm
                initial={{ topic: memory.topic, content: memory.content, keep: !!memory.keep, keep_reason: memory.keep_reason ?? "" }}
                busy={busy}
                onSave={(d) => void save(memory.id, d)}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <>
                <div className="memories__head">
                  <span className="memories__topic">{memory.topic}</span>
                  {memory.keep && <span className="memories__badge" title={memory.keep_reason || "Marked to keep long term"}>Keep</span>}
                </div>
                <div className="memories__content">{memory.content}</div>
                {memory.keep && memory.keep_reason && <div className="memories__why">Why: {memory.keep_reason}</div>}
                <div className="memories__meta">
                  <code title="Memory id">{memory.id}</code>
                  <span>Added {day(memory.added_at)}</span>
                  {memory.updated_at && memory.updated_at !== memory.added_at && <span>Edited {day(memory.updated_at)}</span>}
                  <span>From {sourceLabel(memory.source)}</span>
                  <span className="memories__tools">
                    <button type="button" className="btn btn-ghost" onClick={() => void toggleKeep(memory)}>
                      {memory.keep ? "Unmark" : "Keep long term"}
                    </button>
                    <button type="button" className="btn btn-ghost" onClick={() => { setEditing(memory.id); setAdding(false); }}>Edit</button>
                    <button type="button" className="btn btn-ghost btn-danger" onClick={() => void remove(memory)}>Forget</button>
                  </span>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
