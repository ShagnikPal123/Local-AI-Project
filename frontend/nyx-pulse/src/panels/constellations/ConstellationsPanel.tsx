/** The four sidebar pages the owner asked for (2026-10-11, from the Claude app's sidebar), each with a space / maths name and a
 *  plain subtitle so they stay findable: Constellations (Projects), Quasars (Artifacts), Orbits (Scheduled), Fractal (Design).
 *  Data and rules live in projects.py / scheduled.py; nothing here runs code. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import "./constellations.css";

interface Group { id: string; name: string; about?: string; auto: boolean; tabs: string[] }
interface Artifact { id: string; title: string; kind: string; note: string; project_id: string; ref: string; created: number }
interface Project { id: string; name: string; goal: string; tabs: string[]; groups: Group[]; members: Record<string, string[]>; artifacts: Artifact[] }
interface Avatar { id: string; name: string }
interface Task {
  id: string; title: string; prompt: string; repeat: string; every_minutes: number; time: string; days: number[]; avatar: string;
  enabled: boolean; calendar: boolean; last_run: number; last_reply: string; last_ok: boolean; next: number; at: number;
}

const TABS = ["nyx", "code", "research", "learn", "agents", "avatars", "office", "design", "connectors", "computer", "trading", "equalize"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const REPEAT_WORDS: Record<string, string> = { once: "Once", every: "Every few minutes", daily: "Every day", weekdays: "Weekdays", weekly: "Chosen days" };

function when(seconds: number): string {
  if (!seconds) return "—";
  return new Date(seconds * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" });
}

function Head({ name, plain, about }: { name: string; plain: string; about: string }) {
  return <header className="cx-head"><h1>{name}<small>{plain}</small></h1><p>{about}</p></header>;
}

// --- Constellations: projects -------------------------------------------------------------------------------------

export function ProjectsPanel() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [sel, setSel] = useState("");
  const [name, setName] = useState("");
  const [member, setMember] = useState("");
  const [error, setError] = useState("");
  const project = projects.find((p) => p.id === sel) ?? projects[0];

  const load = useCallback(async () => {
    const r = await api.get<{ projects: Project[] }>("/api/projects");
    if (r.ok) setProjects(r.data.projects); else setError(r.error);
    const a = await api.get<{ avatars: Avatar[] }>("/api/avatars");
    if (a.ok) setAvatars(a.data.avatars);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const act = async (run: () => Promise<{ ok: boolean; error?: string }>) => {
    setError("");
    const r = await run();
    if (!r.ok) setError(r.error ?? "That did not work."); else void load();
  };
  const create = () => act(async () => {
    const r = await api.post<{ project: Project }>("/api/projects", { name });
    if (r.ok) { setName(""); setSel(r.data.project.id); }
    return r;
  });

  return (
    <div className="cx">
      <Head name="Constellations" plain="Projects" about="A big project that groups what belongs together. Tabs are grouped and named for you — rename a group and it stays yours. Add agents, sub-agents and avatars so they work on it." />
      {error && <p className="cx-error" role="alert">{error}</p>}
      <div className="cx-body">
        <div className="cx-card">
          <form className="cx-row" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void create(); }}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New project name" aria-label="New project name" style={{ flex: 1, minWidth: 0 }} />
            <button className="btn btn-primary" disabled={!name.trim()}>Add</button>
          </form>
          <ul className="cx-list">
            {projects.map((p) => (
              <li key={p.id}><button className={`cx-pick ${project?.id === p.id ? "is-on" : ""}`} onClick={() => setSel(p.id)}>
                <b>{p.name}</b><span className="cx-muted">{p.tabs.length} tabs · {Object.values(p.members).flat().length} helpers · {p.artifacts.length} artifacts</span>
              </button></li>
            ))}
          </ul>
          {projects.length === 0 && <p className="cx-muted">No projects yet.</p>}
        </div>

        {project && (
          <div style={{ display: "grid", gap: 14 }}>
            <section className="cx-card">
              <input defaultValue={project.name} key={project.id + project.name} aria-label="Project name" style={{ fontWeight: 600, fontSize: 16 }}
                onBlur={(e) => { if (e.target.value.trim() && e.target.value !== project.name) void act(() => api.put(`/api/projects/${project.id}`, { name: e.target.value })); }} />
              <textarea rows={2} defaultValue={project.goal} key={project.id + "g"} placeholder="What is this project for? Helpers on it read this." aria-label="Project goal"
                onBlur={(e) => { if (e.target.value !== project.goal) void act(() => api.put(`/api/projects/${project.id}`, { goal: e.target.value })); }} />
              <div className="cx-row">
                <button className="btn btn-secondary" onClick={() => { if (confirm(`Delete “${project.name}”? Its artifacts are kept.`)) void act(async () => { const r = await api.del(`/api/projects/${project.id}`); setSel(""); return r; }); }}>Delete project</button>
              </div>
            </section>

            <section className="cx-card">
              <h2>Tabs <small>grouped automatically — edit a group name to change it</small></h2>
              <div className="cx-groups">
                {project.groups.map((g) => (
                  <div className="cx-group" key={g.id}>
                    <input defaultValue={g.name} key={g.id + g.name} aria-label={`Group name (${g.about ?? "your group"})`}
                      onBlur={(e) => { if (e.target.value.trim() && e.target.value !== g.name) void act(() => api.put(`/api/projects/${project.id}/groups/${g.id}`, { name: e.target.value })); }} />
                    <span className="cx-muted">{g.auto ? g.about : "Named by you"}</span>
                    <div className="cx-chips">
                      {g.tabs.map((t) => <button key={t} className="cx-chip" title="Remove from project" onClick={() => void act(() => api.del(`/api/projects/${project.id}/tabs/${t}`))}>{t} ✕</button>)}
                    </div>
                  </div>
                ))}
              </div>
              <div className="cx-chips" aria-label="Add a tab">
                {TABS.filter((t) => !project.tabs.includes(t)).map((t) => <button key={t} className="cx-chip" onClick={() => void act(() => api.post(`/api/projects/${project.id}/tabs`, { tab: t }))}>+ {t}</button>)}
              </div>
            </section>

            <section className="cx-card">
              <h2>On this project <small>agents, sub-agents and avatars</small></h2>
              {(["avatars", "agents", "subagents"] as const).map((kind) => (
                <div key={kind} className="cx-row">
                  <b style={{ width: 84, fontSize: 12 }}>{kind === "subagents" ? "Sub-agents" : kind[0].toUpperCase() + kind.slice(1)}</b>
                  {(project.members[kind] ?? []).map((m) => <button key={m} className="cx-chip" title="Take off the project" onClick={() => void act(() => api.post(`/api/projects/${project.id}/members`, { kind, member: m, on: false }))}>{m} ✕</button>)}
                  {(project.members[kind] ?? []).length === 0 && <span className="cx-muted">none yet</span>}
                </div>
              ))}
              <div className="cx-row">
                <select value={member} onChange={(e) => setMember(e.target.value)} aria-label="Add a helper">
                  <option value="">Add an avatar…</option>
                  {avatars.filter((a) => !(project.members.avatars ?? []).includes(a.id)).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
                <button className="btn btn-secondary" disabled={!member} onClick={() => void act(async () => { const r = await api.post(`/api/projects/${project.id}/members`, { kind: "avatars", member }); setMember(""); return r; })}>Add</button>
              </div>
              <p className="cx-muted">Agents and sub-agents are added by name from chat: “put the Researcher agent on {project.name}”.</p>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Quasars: artifacts -------------------------------------------------------------------------------------------

export function ArtifactsPanel() {
  const [items, setItems] = useState<Artifact[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [kind, setKind] = useState("idea");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const [a, p] = await Promise.all([api.get<{ artifacts: Artifact[]; kinds: string[] }>("/api/artifacts"), api.get<{ projects: Project[] }>("/api/projects")]);
    if (a.ok) { setItems(a.data.artifacts); setKinds(a.data.kinds); } else setError(a.error);
    if (p.ok) setProjects(p.data.projects);
  }, []);
  useEffect(() => { void load(); }, [load]);
  const projectName = (id: string) => projects.find((p) => p.id === id)?.name ?? "No project";
  const add = async () => {
    const r = await api.post("/api/artifacts", { title, note, kind, project_id: filter });
    if (r.ok) { setTitle(""); setNote(""); void load(); } else setError(r.error);
  };
  const shown = items.filter((a) => !filter || a.project_id === filter);
  return (
    <div className="cx">
      <Head name="Quasars" plain="Artifacts" about="Everything you and Ichos create — new ideas, plans, designs, code. Keep them loose or attach them to a project." />
      {error && <p className="cx-error" role="alert">{error}</p>}
      <section className="cx-card">
        <div className="cx-row">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" aria-label="Artifact title" style={{ flex: 1, minWidth: 160 }} />
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">{kinds.map((k) => <option key={k}>{k}</option>)}</select>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Project">
            <option value="">All / no project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="btn btn-primary" disabled={!title.trim()} onClick={() => void add()}>Add</button>
        </div>
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Notes (optional)" aria-label="Notes" />
      </section>
      <ul className="cx-items">
        {shown.map((a) => (
          <li className="cx-item" key={a.id}>
            <div><b>{a.title}</b><span className="cx-muted">{a.kind} · {projectName(a.project_id)} · {when(a.created)}{a.note ? ` — ${a.note.slice(0, 120)}` : ""}</span></div>
            <span className="cx-row">
              <select value={a.project_id} aria-label="Move to project" onChange={(e) => void api.put(`/api/artifacts/${a.id}/project`, { project_id: e.target.value }).then(load)}>
                <option value="">No project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <button className="btn btn-secondary" onClick={() => void api.del(`/api/artifacts/${a.id}`).then(load)}>Remove</button>
            </span>
          </li>
        ))}
      </ul>
      {shown.length === 0 && <p className="cx-muted">Nothing here yet. Ideas and creations you add show up here.</p>}
    </div>
  );
}

// --- Orbits: scheduled --------------------------------------------------------------------------------------------

const BLANK = { title: "", prompt: "", repeat: "daily", time: "08:00", every_minutes: 60, days: [0], avatar: "", calendar: false };

export function ScheduledPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [draft, setDraft] = useState({ ...BLANK });
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const [t, a] = await Promise.all([api.get<{ tasks: Task[] }>("/api/scheduled"), api.get<{ avatars: Avatar[] }>("/api/avatars")]);
    if (t.ok) setTasks(t.data.tasks); else setError(t.error);
    if (a.ok) setAvatars(a.data.avatars);
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);
  const set = (patch: Partial<typeof BLANK>) => setDraft((d) => ({ ...d, ...patch }));
  const add = async () => {
    setError("");
    const r = await api.post("/api/scheduled", draft);
    if (r.ok) { setDraft({ ...BLANK }); void load(); } else setError(r.error);
  };
  return (
    <div className="cx">
      <Head name="Orbits" plain="Scheduled" about="Tell Ichos once what to do and when: read email every morning, send a daily summary, text someone on Friday. An avatar does each task, so its Allow / Ask rules decide what it may touch." />
      {error && <p className="cx-error" role="alert">{error}</p>}
      <section className="cx-card">
        <h2>New scheduled task</h2>
        <div className="cx-row">
          <input value={draft.title} onChange={(e) => set({ title: e.target.value })} placeholder="Name, e.g. Morning mail" aria-label="Task name" style={{ flex: 1, minWidth: 160 }} />
          <select value={draft.avatar} onChange={(e) => set({ avatar: e.target.value })} aria-label="Who does it">
            <option value="">Who does it…</option>{avatars.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <textarea rows={3} value={draft.prompt} onChange={(e) => set({ prompt: e.target.value })} aria-label="What to do"
          placeholder="What should it do? e.g. Read my unread email and send me a two-line summary." />
        <div className="cx-row">
          <select value={draft.repeat} onChange={(e) => set({ repeat: e.target.value })} aria-label="Repeat">
            {Object.entries(REPEAT_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {draft.repeat === "every" ? (
            <label className="cx-row">every <input type="number" min={5} value={draft.every_minutes} onChange={(e) => set({ every_minutes: Number(e.target.value) })} style={{ width: 80 }} /> min</label>
          ) : draft.repeat !== "once" && <label className="cx-row">at <input type="time" value={draft.time} onChange={(e) => set({ time: e.target.value })} /></label>}
          {draft.repeat === "weekly" && DAYS.map((d, i) => (
            <label key={d} className="cx-chip"><input type="checkbox" checked={draft.days.includes(i)} onChange={(e) => set({ days: e.target.checked ? [...draft.days, i] : draft.days.filter((x) => x !== i) })} />{d}</label>
          ))}
          <button className="btn btn-primary" disabled={!draft.title.trim() || !draft.prompt.trim()} onClick={() => void add()}>Schedule</button>
        </div>
        {avatars.length === 0 && <p className="cx-muted">No avatars yet — create one in Avatars first; a task with nobody assigned never runs.</p>}
        <p className="cx-muted">Google Calendar linking is not connected yet (Google sign-in is being fixed). Tasks run from Ichos's own clock while it is open.</p>
      </section>
      <ul className="cx-items">
        {tasks.map((t) => (
          <li key={t.id} className={`cx-item ${t.enabled ? "" : "is-off"}`}>
            <div>
              <b>{t.title}</b>
              <span className="cx-muted">{REPEAT_WORDS[t.repeat]}{t.repeat === "every" ? ` (${t.every_minutes} min)` : t.repeat !== "once" ? ` at ${t.time}` : ""} · {avatars.find((a) => a.id === t.avatar)?.name ?? "nobody assigned"} · next {when(t.next)}</span>
              {t.last_run > 0 && <span className="cx-muted" style={{ color: t.last_ok ? undefined : "var(--color-warn)" }}>Last: {t.last_reply.slice(0, 160) || "done"}</span>}
            </div>
            <span className="cx-row">
              <button className="btn btn-secondary" disabled={!t.avatar} onClick={() => void api.post(`/api/scheduled/${t.id}/run`, {}).then(load)}>Run now</button>
              <button className="btn btn-secondary" onClick={() => void api.put(`/api/scheduled/${t.id}`, { enabled: !t.enabled }).then(load)}>{t.enabled ? "Pause" : "Resume"}</button>
              <button className="btn btn-secondary" onClick={() => void api.del(`/api/scheduled/${t.id}`).then(load)}>Remove</button>
            </span>
          </li>
        ))}
      </ul>
      {tasks.length === 0 && <p className="cx-muted">Nothing scheduled.</p>}
    </div>
  );
}

// --- Fractal: design ----------------------------------------------------------------------------------------------

const TEMPLATES: { id: string; name: string; about: string; brief: string }[] = [
  { id: "phone", name: "Phone app", about: "Portrait, thumb-reachable, iOS / Android", brief: "a phone app (portrait, 390×844, thumb-reach navigation)" },
  { id: "website", name: "Website", about: "Multi-section marketing or content site", brief: "a responsive website with a header, hero, sections and footer" },
  { id: "landing", name: "Landing page", about: "One page, one goal, strong first screen", brief: "a single landing page with one clear call to action" },
  { id: "desktop", name: "Desktop app", about: "Windows-style app with panes and a toolbar", brief: "a Windows desktop application with a sidebar, toolbar and content pane" },
  { id: "dashboard", name: "Dashboard", about: "Cards, charts and filters", brief: "an admin dashboard with stat cards, charts and a data table" },
  { id: "tablet", name: "Tablet app", about: "Split view, landscape friendly", brief: "a tablet app with a split view that works in landscape and portrait" },
  { id: "game", name: "Game interface", about: "HUD, menus and inventory", brief: "a game interface: main menu, in-game HUD and an inventory screen" },
  { id: "extension", name: "Browser extension", about: "Popup and side panel", brief: "a browser extension popup and side panel" },
];

export function DesignPanel() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState("");
  const [idea, setIdea] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { void api.get<{ projects: Project[] }>("/api/projects").then((r) => { if (r.ok) setProjects(r.data.projects); }); }, []);
  const start = async (t: (typeof TEMPLATES)[number]) => {
    setError("");
    const title = `${t.name}${idea.trim() ? ` — ${idea.trim().slice(0, 60)}` : ""}`;
    const r = await api.post("/api/artifacts", { title, kind: "design", note: t.brief, project_id: project });
    if (!r.ok) { setError(r.error); return; }
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "nyx" } }));
    const text = `Let's design ${t.brief}${idea.trim() ? ` for: ${idea.trim()}` : ""}. Start by asking me the 3 things you most need to know (who it is for, the feel, the key screens), then propose a layout and build it with me step by step.`;
    window.setTimeout(() => window.dispatchEvent(new CustomEvent("nyx:chat-send", { detail: { text } })), 400);
  };
  return (
    <div className="cx">
      <Head name="Fractal" plain="Design" about="Design apps and sites with Ichos. Pick a starting point, say what it is for, and you build it together in chat; the result is saved as an artifact." />
      {error && <p className="cx-error" role="alert">{error}</p>}
      <div className="cx-row">
        <input value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="What is it for? (optional)" aria-label="What is it for" style={{ flex: 1, minWidth: 200 }} />
        <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
          <option value="">No project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
      <div className="cx-tpl">
        {TEMPLATES.map((t) => (
          <button key={t.id} onClick={() => void start(t)}><span className="cx-frame" aria-hidden="true" /><b>{t.name}</b><span className="cx-muted">{t.about}</span></button>
        ))}
      </div>
    </div>
  );
}
