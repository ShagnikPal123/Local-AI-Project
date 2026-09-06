/** Find-or-create a tab (ROADMAP CC2, CC4, CC6, CC9).
 *
 * One box does both jobs: type what you call the thing, and it either finds the
 * tab or offers to build one. That is the flow Shagnik described — searching for
 * a tab that does not exist should lead to creating it, not to a dead end.
 *
 * Creating now asks two questions rather than one. The old version posted the
 * search text straight to the designer, so "budget" produced a tab named whatever
 * the model felt like, with contents guessed from a single word. A name and a
 * description are different things: the name is the label in the bar and belongs
 * to the user, the description is the brief the designer works from.
 *
 * The backend takes only a description, so the name is carried into the brief and
 * then re-applied with a PATCH — the user's chosen label always wins over the
 * model's, without touching the Python.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type { TabSpec } from "../panels/DynamicTab";

interface SearchHit {
  id: string;
  label: string;
  source: string;
  score: number;
  matched: string[];
}

/** Matches the server-side cap in dynamic_tabs.build_spec. */
const MAX_LABEL = 40;

export function TabFinder({ onOpen, onCreated, onClose }: {
  onOpen: (tabId: string) => void;
  onCreated: (spec: TabSpec) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [offerCreate, setOfferCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  // The create form is a separate step so the search box stays a search box.
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");

  useEffect(() => {
    if (!query.trim()) {
      setHits([]);
      setOfferCreate(false);
      return;
    }
    let alive = true;
    const timer = setTimeout(async () => {
      const result = await api.get<{ results: SearchHit[]; offer_create: boolean }>(
        `/api/tabs/search?q=${encodeURIComponent(query)}`,
      );
      if (!alive || !result.ok) return;
      setHits(result.data.results);
      setOfferCreate(result.data.offer_create);
    }, 250);
    return () => { alive = false; clearTimeout(timer); };
  }, [query]);

  function openForm() {
    // Seed the name from whatever they were searching for; it is almost always
    // what they want the tab called.
    setName((current) => current || query.trim().slice(0, MAX_LABEL));
    setPurpose((current) => current || "");
    setFormOpen(true);
    setError("");
  }

  async function create() {
    const label = name.trim();
    const brief = purpose.trim();
    if (!label) { setError("Give the tab a name."); return; }
    if (!brief) { setError("Say what the tab should do — that is what gets designed."); return; }

    setCreating(true);
    setError("");
    const result = await api.post<{ tab: TabSpec }>("/api/tabs/from-description", {
      // The name is part of the brief as well as the label, so the designer picks
      // blocks that suit a tab called this.
      description: `Tab name: "${label}". What it should do: ${brief}`,
      name: label,
    });

    if (!result.ok) {
      setCreating(false);
      setError(result.error);
      return;
    }

    let spec = result.data.tab;
    // Hold the model to the user's name. A failure here is not worth blocking on:
    // the tab exists and works, it is just called something else.
    if (spec.label !== label) {
      const renamed = await api.patch<{ tab: TabSpec }>(`/api/tabs/${spec.id}`, { label });
      if (renamed.ok) spec = renamed.data.tab;
    }
    setCreating(false);
    onCreated(spec);
  }

  const field: React.CSSProperties = {
    width: "100%", padding: "10px 12px", background: "var(--color-nav)",
    color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
    boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 14,
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(10,11,18,0.72)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        paddingTop: "12vh", zIndex: 50,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "100%", maxWidth: 520, padding: 18, maxHeight: "76vh", overflowY: "auto" }}
      >
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
          placeholder="Find a tab, or describe one to create…"
          style={{ ...field, fontSize: 15, padding: "11px 13px" }}
        />

        {error && (
          <div style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 10 }}>{error}</div>
        )}

        {!formOpen && hits.length > 0 && (
          <div style={{ marginTop: 12 }}>
            {hits.map((hit) => (
              <button
                key={`${hit.source}-${hit.id}`}
                onClick={() => { onOpen(hit.id); onClose(); }}
                style={{
                  display: "block", width: "100%", textAlign: "left", padding: "9px 11px",
                  marginBottom: 5, borderRadius: "var(--radius)", background: "var(--color-nav)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13 }}>{hit.label}</span>
                  <span style={{ fontSize: 10, textTransform: "uppercase", color: "var(--color-neutral-600)" }}>
                    {hit.source}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 2 }}>
                  matched: {hit.matched.join(", ")}
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Creating is always available, not only when the search finds nothing —
            wanting a second tab about something is not the same as a dead end. */}
        {!formOpen && (
          <div style={{ marginTop: 12 }}>
            {offerCreate && (
              <div style={{ fontSize: 13, color: "var(--color-neutral-400)", marginBottom: 9, lineHeight: 1.6 }}>
                No tab matches that. Want one built for it? The agent designs the layout; it is
                added to your install only.
              </div>
            )}
            <button className="btn btn-primary" onClick={openForm}>
              {hits.length > 0 ? "Create a new tab instead" : "Create a tab"}
            </button>
          </div>
        )}

        {formOpen && (
          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label className="label" htmlFor="tab-name" style={{ display: "block", marginBottom: 6 }}>
                Name
              </label>
              <input
                id="tab-name"
                value={name}
                maxLength={MAX_LABEL}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
                placeholder="Budget"
                style={field}
              />
              <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 4 }}>
                What it is called in the tab bar. {MAX_LABEL - name.length} characters left.
              </div>
            </div>

            <div>
              <label className="label" htmlFor="tab-purpose" style={{ display: "block", marginBottom: 6 }}>
                What should this tab do?
              </label>
              <textarea
                id="tab-purpose"
                value={purpose}
                rows={4}
                onChange={(e) => setPurpose(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") onClose();
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void create(); }
                }}
                placeholder="Track monthly spending against a target, with a running list of one-off costs and a note for next month."
                style={{ ...field, resize: "vertical", lineHeight: 1.6 }}
              />
              <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 4, lineHeight: 1.5 }}>
                This is the brief the agent designs from, and it is what tab search matches on
                later. The more concrete it is, the better the layout.
              </div>
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="btn btn-primary" disabled={creating} onClick={() => void create()}>
                {creating ? "Designing the tab…" : "Create tab"}
              </button>
              <button
                className="btn btn-secondary"
                disabled={creating}
                onClick={() => { setFormOpen(false); setError(""); }}
              >
                Back
              </button>
              <span style={{ fontSize: 11, color: "var(--color-neutral-600)", marginLeft: "auto" }}>
                Ctrl+Enter to create
              </span>
            </div>
          </div>
        )}

        {!formOpen && !query.trim() && (
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 12, lineHeight: 1.6 }}>
            Search by whatever you call it — "my email thing" will find a tab described as
            handling email, even if it is named something else.
          </div>
        )}
      </div>
    </div>
  );
}
