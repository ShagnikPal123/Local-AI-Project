/** Design Research (design_research.py): study how a site looks, keep what is good, and design with it.
 *
 * The owner's Design Masterplan research log as a page: give it an address (and what to look at); it measures the
 * colours, fonts, corners and spacing, writes what is good and a prompt that reproduces the look, and keeps the note.
 * Tabs Nyx designs read these notes. "Add to Masterplan" copies an entry into DESIGN_MASTERPLAN.md for Claude. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import "./design.css";

interface Tokens { colours: string[]; fonts: string[]; radii: string[]; type_sizes: string[]; spacing: string[]; theme: string;
  layout: { grid: number; flex: number } }
interface Entry { id: string; name: string; url: string; at: number; focus: string; tokens: Tokens; good: string;
  reproduce: string; principles: string[]; use_for: string; model: string }

export function DesignResearchPanel() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [hasPlan, setHasPlan] = useState(false);
  const [url, setUrl] = useState("");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const r = await api.get<{ entries: Entry[]; masterplan: boolean }>("/api/design-research");
    if (r.ok) { setEntries(r.data.entries); setHasPlan(r.data.masterplan); } else setNote(r.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const study = async () => {
    setBusy("study"); setNote("");
    const r = await api.post<{ entry: Entry }>("/api/design-research", { url: url.trim(), focus }, 120000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setUrl(""); setFocus("");
    await load();
  };

  const toPlan = async (entry: Entry) => {
    setBusy(entry.id);
    const r = await api.post<{ added: boolean; why?: string }>(`/api/design-research/${entry.id}/masterplan`, {});
    setBusy("");
    setNote(r.ok ? (r.data.added ? `Added “${entry.name}” to the Design Masterplan.` : r.data.why ?? "Already there.") : r.error);
  };

  const remove = async (entry: Entry) => {
    await api.del(`/api/design-research/${entry.id}`);
    await load();
  };

  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setNote("Copied the prompt."); } catch { setNote("The browser refused the clipboard."); }
  };

  return (
    <div className="dr">
      <header>
        <h1>Design Research</h1>
        <p className="dr-muted">Study how a site looks. Nyx keeps what is good — the tokens and the principles, never the page itself — and designs your tabs with it.</p>
      </header>

      <form className="dr-bar" onSubmit={(e) => { e.preventDefault(); void study(); }}>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://linear.app" aria-label="Site to study" inputMode="url" />
        <input value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="What to look at (optional) — the cards, the pricing page…" aria-label="What to look at" />
        <button className="btn btn-primary" disabled={!!busy || !url.trim()}>{busy === "study" ? "Studying…" : "Study"}</button>
      </form>
      {note && <p className="dr-note" role="status">{note}</p>}

      {entries.length === 0 && <p className="dr-muted">Nothing studied yet. Start with a site whose look you like.</p>}
      <div className="dr-grid">
        {entries.map((entry) => (
          <article key={entry.id} className="dr-card">
            <header>
              <b>{entry.name}</b>
              <a href={entry.url} target="_blank" rel="noreferrer">{entry.url.replace(/^https?:\/\//, "").slice(0, 40)}</a>
            </header>
            <div className="dr-swatches" aria-label="Colours it uses most">
              {entry.tokens.colours.slice(0, 8).map((c) => <span key={c} title={c} style={{ background: c }} />)}
              <small className="dr-muted">{entry.tokens.theme}</small>
            </div>
            <p className="dr-tokens">
              {entry.tokens.fonts.length > 0 && <>Fonts {entry.tokens.fonts.join(", ")} · </>}
              {entry.tokens.radii.length > 0 && <>Corners {entry.tokens.radii.join(", ")} · </>}
              {entry.tokens.type_sizes.length > 0 && <>Type {entry.tokens.type_sizes.slice(0, 4).join(", ")}</>}
            </p>
            {entry.good && <p>{entry.good}</p>}
            {entry.principles.length > 0 && <ul>{entry.principles.map((p) => <li key={p}>{p}</li>)}</ul>}
            {entry.use_for && <p className="dr-muted">Use it for: {entry.use_for}</p>}
            {entry.reproduce && (
              <details>
                <summary>Prompt that reproduces it</summary>
                <p className="dr-prompt">{entry.reproduce}</p>
                <button className="btn btn-secondary" onClick={() => void copy(entry.reproduce)}>Copy Prompt</button>
              </details>
            )}
            <footer>
              <small className="dr-muted">{new Date(entry.at * 1000).toLocaleDateString()} · {entry.model}</small>
              <span>
                {hasPlan && <button className="btn btn-secondary" disabled={busy === entry.id} onClick={() => void toPlan(entry)}>Add to Masterplan</button>}
                <button className="btn" onClick={() => void remove(entry)} aria-label={`Remove ${entry.name}`}>Remove</button>
              </span>
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}
