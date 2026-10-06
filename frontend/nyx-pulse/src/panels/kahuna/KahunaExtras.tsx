/** The Big Kahuna tab's working sections: training progress, the scoreboard, templates and suggested tabs. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../components/chat/Icon";

interface Job { id: string; kind: string; state: string; progress: number; message: string; log?: string[];
  metrics?: Record<string, number | string>; result?: { version?: string; metrics?: Record<string, unknown> } | null }

export function TrainingProgress() {
  const [job, setJob] = useState<Job | null>(null);
  const load = useCallback(async () => {
    const result = await api.get<{ jobs: Job[] }>("/api/identity0/jobs");
    if (result.ok) setJob(result.data.jobs.find((j) => j.kind === "train_nano") ?? null);
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [load]);
  if (!job) return null;
  const pct = Math.round(job.progress * 100);
  const live = job.state === "running" || job.state === "queued";
  return (
    <div className="kh-job" aria-live="polite">
      <div className="kh-job__row">
        <span className={`kh-stage kh-stage--${live ? "twin" : job.state === "done" ? "solo" : "collaborate"}`}>{job.state}</span>
        <span className="kh-muted">{job.message}</span>
      </div>
      <div className="kh-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
           aria-label="Training progress"><span style={{ width: `${pct}%` }} /></div>
      {live && <button className="kh-btn" onClick={() => void api.post(`/api/identity0/jobs/${job.id}/cancel`, {})}>Stop</button>}
    </div>
  );
}

interface Score { member: string; suite: string; n: number; score: number; by_category: Record<string, number>; avg_ms: number }

export function Scoreboard({ members }: { members: string[] }) {
  const [rows, setRows] = useState<Score[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const result = await api.get<{ scoreboard: Score[]; running: string | null }>("/api/identity0/scoreboard");
    if (result.ok) { setRows(result.data.scoreboard); setRunning(result.data.running); }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);
  const run = async (member: string) => {
    const result = await api.post("/api/identity0/scoreboard/run", { member });
    if (!result.ok) setError(result.error); else { setError(""); setRunning(member); }
  };
  const categories = Array.from(new Set(rows.flatMap((r) => Object.keys(r.by_category))));
  return (
    <section className="kh-card kh-card--wide" aria-label="Scoreboard">
      <h2><Icon name="bolt" size={16} /> Scoreboard</h2>
      <p className="kh-muted">The same 20 questions to every model, checked the same way (numbers, words, formats, code that
        parses) — so "better than the others" is measured, not claimed.</p>
      <div className="kh-row">
        {members.map((m) => (
          <button key={m} className="kh-btn" disabled={Boolean(running)} onClick={() => void run(m)}>Score {m.split(":").slice(1).join(":") || m}</button>
        ))}
        {running && <span className="kh-muted">Scoring {running}…</span>}
      </div>
      {error && <p className="kh-error">{error}</p>}
      {rows.length > 0 && (
        <div className="kh-table-wrap">
          <table className="kh-table">
            <thead><tr><th scope="col">Model</th><th scope="col">Score</th>{categories.map((c) => <th key={c} scope="col">{c}</th>)}<th scope="col">Avg time</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.member}|${r.suite}`}>
                  <td>{r.member}</td><td><b>{Math.round(r.score * 100)}%</b></td>
                  {categories.map((c) => <td key={c}>{r.by_category[c] == null ? "—" : `${Math.round(r.by_category[c] * 100)}%`}</td>)}
                  <td>{(r.avg_ms / 1000).toFixed(1)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

interface Template { id: string; category: string; kind: string; title: string; description: string; tags: string[] }

export function TemplatesGallery() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [list, setList] = useState<Template[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [using, setUsing] = useState<Template | null>(null);
  const [folder, setFolder] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api.get<{ templates: Template[]; categories: string[] }>(
        `/api/identity0/templates?q=${encodeURIComponent(query)}&category=${encodeURIComponent(category)}`).then((result) => {
        if (result.ok) { setList(result.data.templates); setCategories(result.data.categories); }
      });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [query, category]);
  const use = async () => {
    if (!using) return;
    const result = await api.post<{ kind: string; folder?: string; label?: string; text?: string; written?: string }>(
      `/api/identity0/templates/${using.id}/use`, { folder, name });
    if (!result.ok) { setNote(result.error); return; }
    const made = result.data;
    setNote(made.kind === "files" ? `Created ${made.folder}` : made.kind === "tab" ? `Made the ${made.label} tab`
      : made.written ? `Wrote ${made.written}` : "Copied below");
    if (made.kind === "doc" && made.text && !made.written) void navigator.clipboard?.writeText(made.text).catch(() => undefined);
    if (made.kind === "tab") window.dispatchEvent(new CustomEvent("nyx:tabs-changed"));
  };
  return (
    <section className="kh-card kh-card--wide" aria-label="Templates">
      <h2><Icon name="file" size={16} /> Templates</h2>
      <div className="kh-row">
        <input className="kh-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search: react app, resume, budget tab…" aria-label="Search templates" />
        <button className={`kh-chip${category === "" ? " is-on" : ""}`} onClick={() => setCategory("")}>All</button>
        {categories.map((c) => <button key={c} className={`kh-chip${category === c ? " is-on" : ""}`} onClick={() => setCategory(c)}>{c}</button>)}
      </div>
      <ul className="kh-templates">
        {list.map((t) => (
          <li key={t.id}>
            <button className={`kh-template${using?.id === t.id ? " is-on" : ""}`} onClick={() => { setUsing(t); setNote(""); }}>
              <b>{t.title}</b><span>{t.description}</span><small>{t.category}</small>
            </button>
          </li>
        ))}
      </ul>
      {using && (
        <div className="kh-use">
          <p><b>{using.title}</b> — {using.kind === "files" ? "files go into a new folder inside the folder you name" : using.kind === "tab" ? "becomes a new tab" : "a document you can save or copy"}.</p>
          {using.kind !== "tab" && <input className="kh-input" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Folder (e.g. C:\Users\you\Projects)" aria-label="Folder" />}
          <input className="kh-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" aria-label="Name" />
          <button className="kh-btn kh-btn--primary" onClick={() => void use()}>Use template</button>
          {note && <span className="kh-muted">{note}</span>}
        </div>
      )}
    </section>
  );
}

interface Proposal { id: string; title: string; why: string }

export function SuggestedTabs() {
  const [list, setList] = useState<Proposal[]>([]);
  const load = useCallback(async () => {
    const result = await api.get<{ proposals: Proposal[] }>("/api/identity0/tabs");
    if (result.ok) setList(result.data.proposals);
  }, []);
  useEffect(() => { void load(); }, [load]);
  const decide = async (id: string, decision: "approve" | "dismiss") => {
    const result = await api.post<{ proposals: Proposal[] }>(`/api/identity0/tabs/${id}/${decision}`, {});
    if (result.ok) {
      setList(result.data.proposals);
      if (decision === "approve") window.dispatchEvent(new CustomEvent("nyx:tabs-changed"));
    }
  };
  return (
    <section className="kh-card" aria-label="Tabs it thinks you need">
      <h2><Icon name="sparkle" size={16} /> Tabs it thinks you need</h2>
      {list.length === 0 ? <p className="kh-muted">Nothing yet — it suggests tabs for things you keep asking about.</p> : (
        <ul className="kh-proposals">
          {list.map((p) => (
            <li key={p.id}>
              <div><b>{p.title}</b><p className="kh-muted">Because {p.why}.</p></div>
              <div className="kh-row">
                <button className="kh-btn kh-btn--primary" onClick={() => void decide(p.id, "approve")}>Create</button>
                <button className="kh-btn" onClick={() => void decide(p.id, "dismiss")}>Not now</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
