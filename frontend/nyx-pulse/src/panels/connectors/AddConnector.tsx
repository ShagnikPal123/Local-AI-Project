/** "Add any site or connector" (Update 1, U9).
 *
 * The owner types a name, a website, an API address or an MCP server URL. Nyx finds it in the catalogue or among the
 * MCP servers it knows, or builds the connection (MCP, API or a website it can read) — then asks only for what is
 * still missing. A key pasted into the box stays on this PC and comes back masked.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { Connector, Draft, Note } from "./types";

const EXAMPLES = ["Vercel", "https://mcp.deepwiki.com/mcp", "stripe.com", "https://api.example.com/v1", "https://news.ycombinator.com"];

export function AddConnector({ initial, onClose, onAdded, onOpen }: {
  initial: string;
  onClose: () => void;
  onAdded: (connector: Connector | null) => void;
  onOpen: (id: string) => void;
}) {
  const [text, setText] = useState(initial);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState<"" | "find" | "add">("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function find(words = text) {
    if (!words.trim()) return;
    setText(words);
    setBusy("find"); setNote(null); setDraft(null); setValues({});
    const result = await api.post<{ draft: Draft }>("/api/connectors/find", { text: words }, 60_000);
    setBusy("");
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setDraft(result.data.draft);
  }

  async function add() {
    if (!draft) return;
    setBusy("add");
    const fields = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()));
    const result = await api.post<{ message: string; connector: Connector | null }>("/api/connectors/add",
      { draft_id: draft.draft_id, fields });
    setBusy("");
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setNote({ ok: true, text: result.data.message });
    onAdded(result.data.connector);
  }

  const missing = draft ? draft.fields.filter((f) => !f.filled && (f.required || f.secret || f.kind === "url")) : [];
  const ready = draft && !draft.blocked && !draft.open &&
    missing.every((f) => !f.required || (values[f.key] ?? "").trim());

  return (
    <div className="cx-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cx-sheet cx-sheet--add" role="dialog" aria-modal="true" aria-labelledby="cx-add-title">
        <header className="cx-sheet__head">
          <span className="cx-mark cx-mark--lg cx-mark--plus" aria-hidden="true">+</span>
          <div className="cx-sheet__title">
            <h2 id="cx-add-title">Add Any App or Site</h2>
            <p className="cx-muted">A name, a website, an API address or an MCP server URL.</p>
          </div>
          <button className="cx-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <form className="cx-find" onSubmit={(e) => { e.preventDefault(); void find(); }}>
          <input ref={input} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
            placeholder="e.g. Linear, https://mcp.example.com/mcp, docs.mysite.com" aria-label="What to add" />
          <button className="btn btn-primary" disabled={busy !== "" || !text.trim()}>{busy === "find" ? "Finding…" : "Find"}</button>
        </form>
        {!draft && (
          <div className="cx-examples">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="cx-chip" onClick={() => void find(example)}>{example}</button>
            ))}
          </div>
        )}

        {draft && (
          <section className="cx-draft" aria-live="polite">
            <div className="cx-draft__head">
              <strong>{draft.name}</strong>
              <span className="cx-pill">{{ catalog: "In the catalogue", known_mcp: "Known MCP server", mcp: "New MCP server",
                api: "New API", website: "Website", model: "AI model", proposed: "New connector" }[draft.source] ?? draft.source}</span>
            </div>
            {draft.base_url && <code className="cx-draft__url">{draft.base_url}</code>}
            <p className={draft.blocked ? "cx-note is-error" : "cx-lede"}>{draft.message}</p>
            {(draft.open || draft.suggest) && (
              <div className="cx-actions">
                <button className="btn btn-primary" onClick={() => onOpen(draft.open || draft.suggest)}>
                  Open {draft.open ? draft.name : "the connector"}
                </button>
              </div>
            )}
            {!draft.open && !draft.blocked && (
              <form className="cx-form" onSubmit={(e) => { e.preventDefault(); if (ready) void add(); }}>
                {draft.fields.filter((f) => f.filled).map((f) => (
                  <p key={f.key} className="cx-muted">{f.label}: {f.secret ? f.masked : f.value}</p>
                ))}
                {missing.map((field) => (
                  <label key={field.key} className="cx-field">
                    <span>{field.label}{!field.required && <em> optional</em>}
                      {field.help_url && <a className="cx-field__help" href={field.help_url} target="_blank" rel="noopener noreferrer">Get it ↗</a>}
                    </span>
                    <input type={field.secret ? "password" : "text"} autoComplete="off" spellCheck={false}
                      value={values[field.key] ?? ""} placeholder={field.placeholder ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))} />
                  </label>
                ))}
                <div className="cx-actions">
                  <button className="btn btn-primary" disabled={!ready || busy !== ""}>{busy === "add" ? "Adding…" : `Add ${draft.name}`}</button>
                  <button type="button" className="btn btn-secondary" onClick={() => { setDraft(null); setNote(null); }}>Back</button>
                </div>
              </form>
            )}
          </section>
        )}
        {note && <p className={`cx-note ${note.ok ? "is-ok" : "is-error"}`} aria-live="polite">{note.text}</p>}
      </div>
    </div>
  );
}
