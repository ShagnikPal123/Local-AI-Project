/** A project's folder and drives, opened right in its home in the chat (owner, 2026-10-15: "open drives", "add files
 *  to the main file").
 *
 *  • The places are the project's folder plus its extra drives. A local folder lists here (read-only, folders first);
 *    a Google Drive one (written "drive:<name>") says it opens once Google sign-in works.
 *  • **Add** on a text file copies it into the project's knowledge, so every thread can use it.
 *  • A new drive is added by path; a Google Drive folder by "drive:" and its name. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api";

interface Entry { name: string; path: string; dir: boolean; size: number; text: boolean }
interface Listing { place: { path: string; kind: string; label: string }; path: string; up: string; entries: Entry[]; cut: boolean }

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ProjectFiles({ projectId, folder, drives, onChanged }: {
  projectId: string; folder: string; drives: string[]; onChanged: () => void;
}) {
  const places = [folder, ...drives].filter(Boolean);
  const [path, setPath] = useState(places[0] ?? "");
  const [listing, setListing] = useState<Listing | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  const load = useCallback(async (where: string) => {
    setError(""); setNote("");
    if (!where) { setListing(null); return; }
    const r = await api.get<Listing>(`/api/projects/${projectId}/files?path=${encodeURIComponent(where)}`);
    if (r.ok) setListing(r.data); else { setListing(null); setError(r.error); }
  }, [projectId]);
  useEffect(() => { void load(path); }, [load, path]);

  const addFile = async (entry: Entry) => {
    setError(""); setNote("");
    const r = await api.post<{ doc: { title: string } }>(`/api/projects/${projectId}/files`, { path: entry.path });
    if (r.ok) { setNote(`Added ${r.data.doc.title} to the project.`); onChanged(); } else setError(r.error);
  };
  const addDrive = async () => {
    const value = draft.trim();
    if (!value) return;
    const r = await api.put(`/api/projects/${projectId}`, { drives: [...drives, value] });
    if (!r.ok) { setError(r.error); return; }
    setDraft(""); setAdding(false); setPath(value); onChanged();
  };
  const dropDrive = async (value: string) => {
    const r = await api.put(`/api/projects/${projectId}`, { drives: drives.filter((d) => d !== value) });
    if (r.ok) { if (path.startsWith(value)) setPath(folder); onChanged(); } else setError(r.error);
  };

  return (
    <div className="pj-card pj-files">
      <h3>Folder and drives</h3>
      <div className="pj-files__places" role="group" aria-label="Places">
        {places.map((p) => (
          <span key={p} className={`pj-files__place${listing?.place.path === p || (!listing && path === p) ? " is-on" : ""}`}>
            <button type="button" onClick={() => setPath(p)} title={p}>
              {p.toLowerCase().startsWith("drive:") ? "☁ " : "▭ "}{p.toLowerCase().startsWith("drive:") ? p.slice(6).trim() || "Google Drive" : p.split(/[\\/]/).filter(Boolean).pop() || p}
            </button>
            {p !== folder && <button type="button" className="pj-files__x" onClick={() => void dropDrive(p)} aria-label={`Remove ${p}`} title="Remove this drive">✕</button>}
          </span>
        ))}
        <button type="button" className="pj-act" onClick={() => setAdding((v) => !v)}>＋ Drive</button>
      </div>
      {adding && (
        <form className="ov-lib-form" onSubmit={(e) => { e.preventDefault(); void addDrive(); }}>
          <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Drive path"
            placeholder="D:\Shared\Plans, or drive:Plans for a Google Drive folder" />
          <span><button type="submit" className="btn btn-secondary">Add</button>
            <button type="button" className="btn" onClick={() => setAdding(false)}>Cancel</button></span>
        </form>
      )}
      {places.length === 0 && <p className="pj-hint">Link a folder above, or add a drive, and its files show here.</p>}
      {error && <p className="ov-error">{error}</p>}
      {note && <p className="pj-hint" role="status">{note}</p>}
      {listing && (
        <ul className="pj-files__list" aria-label={listing.path}>
          {listing.up && (
            <li><button type="button" className="pj-files__row" onClick={() => setPath(listing.up)}><span aria-hidden="true">↰</span> Up</button></li>
          )}
          {listing.entries.map((e) => (
            <li key={e.path}>
              {e.dir
                ? <button type="button" className="pj-files__row" onClick={() => setPath(e.path)}><span aria-hidden="true">▸</span> {e.name}</button>
                : <span className="pj-files__row is-file"><span aria-hidden="true">·</span> {e.name}<span className="pj-where">{size(e.size)}</span>
                    {e.text && <button type="button" className="pj-act" onClick={() => void addFile(e)}>Add</button>}</span>}
            </li>
          ))}
          {listing.entries.length === 0 && <li className="pj-hint">Empty folder.</li>}
          {listing.cut && <li className="pj-hint">Showing the first 200.</li>}
        </ul>
      )}
    </div>
  );
}
