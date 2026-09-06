/** Find-or-create a tab (ROADMAP CC2, CC4, CC6, CC9).
 *
 * One box does both jobs: type what you call the thing, and it either finds the
 * tab or offers to build one. That is the flow Shagnik described — searching for
 * a tab that does not exist should lead to creating it, not to a dead end.
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

  async function create() {
    setCreating(true);
    setError("");
    const result = await api.post<{ tab: TabSpec }>("/api/tabs/from-description", {
      description: query,
    });
    setCreating(false);
    if (result.ok) onCreated(result.data.tab);
    else setError(result.error);
  }

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
        style={{ width: "100%", maxWidth: 520, padding: 18 }}
      >
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
          placeholder="Find a tab, or describe one to create…"
          style={{
            width: "100%", padding: "11px 13px", background: "var(--color-nav)",
            color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
            boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 15,
          }}
        />

        {error && (
          <div style={{ fontSize: 12, color: "var(--color-danger)", marginTop: 10 }}>{error}</div>
        )}

        {hits.length > 0 && (
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

        {offerCreate && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 13, color: "var(--color-neutral-400)", marginBottom: 9, lineHeight: 1.6 }}>
              No tab matches that. Want one built for it? The agent designs the layout; it is
              added to your install only.
            </div>
            <button className="btn btn-primary" disabled={creating} onClick={() => void create()}>
              {creating ? "Designing the tab…" : `Create a tab for "${query.slice(0, 40)}"`}
            </button>
          </div>
        )}

        {!query.trim() && (
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 12, lineHeight: 1.6 }}>
            Search by whatever you call it — "my email thing" will find a tab described as
            handling email, even if it is named something else.
          </div>
        )}
      </div>
    </div>
  );
}
