/** A project's knowledge base (Drive doc 1, item 1.28: projects like Claude's). Notes and text files added here are
 *  searched for each thread's task, and the passages that fit go into that thread's brief (project_knowledge.py). */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

interface Doc { id: string; title: string; chars: number; created: number; cut: boolean }

/** Text the browser can read as-is. Anything else (PDFs, images) would arrive as noise, so it is turned away. */
const READABLE = ".txt,.md,.markdown,.csv,.json,.yaml,.yml,.log,.html,.xml,.py,.ts,.tsx,.js,.jsx,.css,.sql,.toml,.ini";
const MAX_FILE = 2_000_000;

export function KnowledgeCard({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const r = await api.get<{ docs: Doc[] }>(`/api/commander/projects/${projectId}/knowledge`);
    if (r.ok) setDocs(r.data.docs); else setError(r.error);
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  const add = async (name: string, body: string) => {
    setError("");
    const r = await api.post(`/api/commander/projects/${projectId}/knowledge`, { title: name, text: body });
    if (!r.ok) { setError(r.error); return false; }
    void load();
    return true;
  };
  const files = async (list: FileList | null) => {
    for (const file of Array.from(list ?? [])) {
      if (file.size > MAX_FILE) { setError(`${file.name} is over 2 MB. Add the part that matters as a note.`); continue; }
      await add(file.name, await file.text());
    }
  };

  return (
    <section className="cx-card">
      <h2>Knowledge <small>notes and text files this project's threads draw on</small></h2>
      {docs.length === 0 && <p className="cx-muted">Nothing yet. Add specs, notes or docs, and each thread gets the parts that fit its task.</p>}
      {docs.length > 0 && (
        <div className="cx-chips">
          {docs.map((d) => (
            <button key={d.id} className="cx-chip" title={`${d.chars.toLocaleString()} characters${d.cut ? " (cut to fit)" : ""}. Remove from the project.`}
              onClick={() => { if (confirm(`Remove “${d.title}” from this project's knowledge?`)) void api.del(`/api/commander/projects/${projectId}/knowledge/${d.id}`).then(load); }}>
              {d.title} ✕
            </button>
          ))}
        </div>
      )}
      <form className="cx-knowledge" onSubmit={(e) => { e.preventDefault(); void add(title, text).then((ok) => { if (ok) { setTitle(""); setText(""); } }); }}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)" aria-label="Note title" />
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste a note, a spec or anything the threads should know" aria-label="Note text" />
        <div className="cx-row">
          <button className="btn btn-secondary" disabled={!text.trim()}>Add note</button>
          <label className="btn btn-secondary">Add text files
            <input type="file" accept={READABLE} multiple hidden onChange={(e) => { void files(e.target.files); e.target.value = ""; }} />
          </label>
        </div>
      </form>
      {error && <p className="cx-error" role="alert">{error}</p>}
    </section>
  );
}
