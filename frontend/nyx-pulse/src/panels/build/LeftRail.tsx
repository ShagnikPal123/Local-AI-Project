/** Where parts come from: real components, parts you saved, and this build's own parts. */

import { useEffect, useMemo, useState } from "react";
import { SHAPES } from "./PartEditor";
import { buildApi, type CatalogEntry, type FeatureType, type LibraryEntry, type Snapshot } from "./types";

type Tab = "catalog" | "saved" | "build";

export interface LeftRailProps {
  snapshot: Snapshot | null;
  libraryVersion: number;
  busy: boolean;
  onPlaceCatalog: (catalogId: string) => void;
  onPlaceLibrary: (libraryId: string) => void;
  onPlacePart: (partId: string) => void;
  onEditPart: (partId: string) => void;
  onNewPart: (type: FeatureType) => void;
  onDuplicatePart: (partId: string) => void;
  onDeletePart: (partId: string) => void;
  onSaveToLibrary: (partId: string) => void;
  onLibraryChanged: () => void;
}

const money = (value: number | string | undefined) => (typeof value === "number" && value > 0 ? `$${value.toFixed(value < 10 ? 2 : 0)}` : "");

export function LeftRail(props: LeftRailProps) {
  const [tab, setTab] = useState<Tab>("catalog");
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [library, setLibrary] = useState<LibraryEntry[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void buildApi.catalog().then((result) => {
      if (!alive) return;
      if (result.ok) setCatalog(result.data.parts);
      else setError(result.error);
    });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    void buildApi.library().then((result) => {
      if (alive && result.ok) setLibrary(result.data.parts);
    });
    return () => { alive = false; };
  }, [props.libraryVersion]);

  const groups = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = (catalog ?? []).filter((entry) => {
      const text = `${entry.name} ${entry.group} ${entry.summary} ${entry.tags.join(" ")}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
    const out = new Map<string, CatalogEntry[]>();
    hits.forEach((entry) => out.set(entry.group, [...(out.get(entry.group) ?? []), entry]));
    return [...out.entries()];
  }, [catalog, query]);

  const project = props.snapshot?.project;
  const placedCount = (partId: string) => project?.placements.filter((p) => p.part_id === partId).length ?? 0;

  return (
    <aside className="bs-rail" data-tour="rail" aria-label="Parts">
      <div className="segmented bs-tabs" role="tablist">
        {([["catalog", "Catalog"], ["saved", `Saved${library?.length ? ` ${library.length}` : ""}`], ["build", `This build${project?.parts.length ? ` ${project.parts.length}` : ""}`]] as [Tab, string][]).map(([id, text]) => (
          <button key={id} role="tab" aria-selected={tab === id} aria-pressed={tab === id} onClick={() => setTab(id)}>{text}</button>
        ))}
      </div>

      {tab === "catalog" && (
        <div className="bs-rail__body">
          <input className="bs-search" type="search" placeholder="Search boards, sensors, fans…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the catalog" />
          {error && <p className="bs-error">{error}</p>}
          {!catalog && !error && <div className="bs-skeleton-list" aria-label="Loading the catalog">{Array.from({ length: 6 }, (_, i) => <div key={i} className="bs-skeleton" />)}</div>}
          {groups.map(([group, entries]) => (
            <div key={group} className="bs-group">
              <div className="bs-group__title">{group}</div>
              {entries.map((entry) => (
                <div key={entry.id} className="bs-item" title={entry.summary}>
                  <span className="bs-swatch" style={{ background: entry.color }} aria-hidden />
                  <div className="bs-item__text">
                    <div className="bs-item__name">{entry.name}</div>
                    <div className="bs-item__meta">
                      {entry.pin_count ? `${entry.pin_count} pins` : entry.kind}
                      {money(entry.specs.price_usd) && ` · ${money(entry.specs.price_usd)}`}
                    </div>
                  </div>
                  <button className="btn btn-secondary btn-sm" disabled={props.busy || !project} onClick={() => props.onPlaceCatalog(entry.id)} aria-label={`Add ${entry.name} to the build`}>Add</button>
                </div>
              ))}
            </div>
          ))}
          {catalog && !groups.length && <p className="bs-muted">Nothing in the catalog matches. Try the Nyx tab: “draw a bracket for …”.</p>}
        </div>
      )}

      {tab === "saved" && (
        <div className="bs-rail__body">
          {!library && <div className="bs-skeleton-list">{Array.from({ length: 3 }, (_, i) => <div key={i} className="bs-skeleton" />)}</div>}
          {library && !library.length && (
            <p className="bs-muted">Parts you save land here, ready for any build. Select a part in the space and press <b>Save to library</b>.</p>
          )}
          {library?.map((entry) => (
            <div key={entry.id} className="bs-item" title={entry.summary}>
              <span className="bs-swatch" style={{ background: entry.color }} aria-hidden />
              <div className="bs-item__text">
                <div className="bs-item__name">{entry.name}</div>
                <div className="bs-item__meta">{entry.size.map((v) => Math.round(v)).join(" × ")} mm · {entry.features} shapes{entry.pins ? ` · ${entry.pins} pins` : ""}</div>
              </div>
              <button className="btn btn-secondary btn-sm" disabled={props.busy || !project} onClick={() => props.onPlaceLibrary(entry.id)}>Add</button>
              <button className="bs-icon bs-icon--danger" aria-label={`Remove ${entry.name} from the library`} onClick={async () => {
                const result = await buildApi.deleteFromLibrary(entry.id);
                if (result.ok) setLibrary(result.data.parts);
                props.onLibraryChanged();
              }}>×</button>
            </div>
          ))}
        </div>
      )}

      {tab === "build" && (
        <div className="bs-rail__body">
          <div className="bs-group__title">Draw a new part</div>
          <div className="bs-shapes">
            {SHAPES.map((shape) => (
              <button key={shape.type} className="bs-shape" onClick={() => props.onNewPart(shape.type)} title={shape.hint} disabled={!project}>{shape.label}</button>
            ))}
          </div>
          <div className="bs-group__title">Parts in this build</div>
          {!project?.parts.length && <p className="bs-muted">No parts yet. Add one from the catalog, draw one, or ask Nyx.</p>}
          {project?.parts.map((part) => (
            <div key={part.id} className="bs-part">
              <div className="bs-item">
                <span className="bs-swatch" style={{ background: part.color }} aria-hidden />
                <div className="bs-item__text">
                  <div className="bs-item__name">{part.name}</div>
                  <div className="bs-item__meta">{part.kind} · {placedCount(part.id)} in the space{part.source === "ai" ? " · drawn by Nyx" : ""}</div>
                </div>
              </div>
              <div className="bs-part__actions">
                <button className="bs-link" onClick={() => props.onPlacePart(part.id)} disabled={props.busy}>Place</button>
                <button className="bs-link" onClick={() => props.onEditPart(part.id)}>Edit</button>
                <button className="bs-link" onClick={() => props.onDuplicatePart(part.id)} disabled={props.busy}>Duplicate</button>
                <button className="bs-link" onClick={() => props.onSaveToLibrary(part.id)} disabled={props.busy}>Save</button>
                <button className="bs-link bs-link--danger" onClick={() => props.onDeletePart(part.id)} disabled={props.busy}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
