/** Projects inside the chat, like Claude Projects (owner, 2026-10-15, with his project image: "creating a new project
 *  has its folder/file, and it shows its connections to chats, splits, sectors, and such").
 *
 *  • **ProjectsSection** sits in the chat list: every Constellation (starred first) and "+ New project". Opening one
 *    opens the project's main chat (its Commander chat, made the first time), so a project is one conversation that
 *    splits into threads, like Claude's.
 *  • **ProjectHome** sits on top of that main chat: "Hi {name}, let me show you around", then the project's context —
 *    its folder on this PC, instructions, knowledge files, Library items, threads and connections (helpers and tabs) —
 *    and its recent threads. It folds to one line once the chat has messages.
 *
 *  Everything is read from what Constellations and Commander already keep (/api/projects, /api/commander); the only
 *  writes are the folder, the instructions and a knowledge note, each through its existing route. */

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import { ownerName } from "../phrases";
import { ago } from "./OverviewPanel";
import { RAIL_PROJECTS_EVENT } from "../ChatRail";
import { ProjectFiles } from "./ProjectFiles";

// The full setup (tabs, helpers, Library) only loads when opened.
const ProjectSetup = lazy(() => import("../../../panels/constellations/ConstellationsPanel").then((m) => ({ default: m.ProjectSetup })));

interface Balance { counts: { free: number; busy: number; waiting: number; full: number }; advice: string }

interface Project {
  id: string; name: string; goal: string; instructions?: string; starred?: boolean; folder?: string; drives?: string[]; tabs: string[];
  members: Record<string, string[]>; artifacts: { id: string; title: string }[];
}
interface Thread { id: string; chat_id: string; title: string; status: string; line: string; status_label: string; updated: number }
interface Board { groups: { id: string; threads: Thread[] }[]; total: number; needs_you: number }

/** Which project a chat is in: as its main chat ("main") or as one of the threads that main chat started ("thread").
 *  The Overview follows it, so a project's threads stay in view inside any of them. */
export interface ChatProject { projectId: string; mainChatId: string; role: "" | "main" | "thread" }
const NO_PROJECT: ChatProject = { projectId: "", mainChatId: "", role: "" };

export function useChatProject(chatId: string): ChatProject {
  const [found, setFound] = useState<ChatProject>(NO_PROJECT);
  useEffect(() => {
    let alive = true;
    setFound(NO_PROJECT);
    if (!chatId || chatId === "default") return;
    void api.get<{ project_id: string; main_chat_id: string; role: "" | "main" | "thread" }>(
      `/api/commander/chat-project?chat_id=${encodeURIComponent(chatId)}`).then((r) => {
      if (alive && r.ok && r.data.project_id) setFound({ projectId: r.data.project_id, mainChatId: r.data.main_chat_id, role: r.data.role });
    });
    return () => { alive = false; };
  }, [chatId]);
  return found;
}

/** On top of a project's thread: which project it is in, and the way back to the main chat. */
export function ProjectThreadBar({ projectId, onOpenMain }: { projectId: string; onOpenMain: () => void }) {
  const [name, setName] = useState("");
  useEffect(() => {
    let alive = true;
    void api.get<{ project: Project }>(`/api/projects/${projectId}`).then((r) => { if (alive && r.ok) setName(r.data.project.name); });
    return () => { alive = false; };
  }, [projectId]);
  return (
    <button type="button" className="pj-bar" onClick={onOpenMain} title="Back to the project's main chat">
      <span aria-hidden="true">↰</span> <b>{name || "Project"}</b>
      <span className="pj-bar__meta">A thread in this project · back to the main chat</span>
    </button>
  );
}

// --- the list in the chat rail --------------------------------------------------------------------------------------

export function ProjectsSection({ activeProject, onOpenChat }: { activeProject: string; onOpenChat: (chatId: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("nyx.rail.projects") !== "0"; } catch { return true; } });
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const r = await api.get<{ projects: Project[] }>("/api/projects");
    if (r.ok) setProjects(r.data.projects);
  }, []);
  useEffect(() => { void load(); }, [load, activeProject]);
  useEffect(() => { try { localStorage.setItem("nyx.rail.projects", open ? "1" : "0"); } catch { /* not kept */ } }, [open]);
  // "Projects" at the top of the rail opens this list (and starts a new one when there are none) instead of a tab.
  const sectionRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const show = () => {
      setOpen(true);
      if (projects.length === 0) setNaming(true);
      sectionRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };
    window.addEventListener(RAIL_PROJECTS_EVENT, show);
    return () => window.removeEventListener(RAIL_PROJECTS_EVENT, show);
  }, [projects.length]);

  const openProject = async (id: string) => {
    setError("");
    const r = await api.post<{ chat_id: string }>(`/api/commander/projects/${id}/chat`, {});
    if (r.ok) onOpenChat(r.data.chat_id); else setError(r.error);
  };
  const create = async () => {
    const value = name.trim();
    if (!value) return;
    const r = await api.post<{ project: Project }>("/api/projects", { name: value });
    if (!r.ok) { setError(r.error); return; }
    setNaming(false); setName("");
    await load();
    void openProject(r.data.project.id);
  };

  return (
    <section className="pj-rail" aria-label="Projects" ref={sectionRef}>
      <div className="pj-rail__head">
        <button type="button" className="pj-rail__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span aria-hidden="true">{open ? "⌄" : "›"}</span> Projects <span className="ov-n">{projects.length}</span>
        </button>
        <button type="button" className="pj-rail__add" onClick={() => { setOpen(true); setNaming(true); }} aria-label="New project" title="New project">＋</button>
      </div>
      {open && (
        <ul className="pj-rail__list">
          {naming && (
            <li>
              <form onSubmit={(e) => { e.preventDefault(); void create(); }}>
                <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" aria-label="Project name"
                  onKeyDown={(e) => { if (e.key === "Escape") setNaming(false); }} />
              </form>
            </li>
          )}
          {projects.map((p) => (
            <li key={p.id}>
              <button type="button" className={`pj-rail__item${p.id === activeProject ? " is-open" : ""}`} onClick={() => void openProject(p.id)}
                title={p.goal || p.name}>
                <span aria-hidden="true" className="pj-rail__mark">{p.starred ? "★" : "▣"}</span>
                <span className="pj-rail__name">{p.name}</span>
              </button>
            </li>
          ))}
          {projects.length === 0 && !naming && <li className="ov-empty">A project keeps chats, files and helpers together.</li>}
          {error && <li className="ov-error">{error}</li>}
        </ul>
      )}
    </section>
  );
}

// --- the home on top of a project's main chat -----------------------------------------------------------------------

export function ProjectHome({ projectId, empty, onOpenChat, onUseFolder, onShowThreads }: {
  projectId: string; empty: boolean; onOpenChat: (chatId: string) => void; onUseFolder: (folder: string) => void;
  onShowThreads: () => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [docs, setDocs] = useState<{ id: string; title: string }[]>([]);
  const [board, setBoard] = useState<Board | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [panel, setPanel] = useState<"" | "files" | "setup">("");
  const [open, setOpen] = useState(empty);
  const [editing, setEditing] = useState<"" | "folder" | "instructions" | "note">("");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [p, k, b, l] = await Promise.all([
      api.get<{ project: Project }>(`/api/projects/${projectId}`),
      api.get<{ docs: { id: string; title: string }[] }>(`/api/commander/projects/${projectId}/knowledge`),
      api.get<{ board: Board }>(`/api/commander?project_id=${encodeURIComponent(projectId)}`),
      api.get<Balance>(`/api/projects/${projectId}/balance`),
    ]);
    if (p.ok) setProject(p.data.project);
    if (l.ok) setBalance(l.data);
    if (k.ok) setDocs(k.data.docs);
    if (b.ok) setBoard(b.data.board);
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setOpen(empty); }, [projectId, empty]);
  useEffect(() => { setPanel(""); }, [projectId]);

  if (!project) return null;
  const name = ownerName();
  const threads = (board?.groups ?? []).flatMap((g) => g.threads).sort((a, b) => b.updated - a.updated);
  const helpers = Object.values(project.members || {}).flat();

  const save = async () => {
    setError("");
    const value = draft.trim();
    const r = editing === "note"
      ? await api.post(`/api/commander/projects/${projectId}/knowledge`, { title: value.split("\n")[0].slice(0, 80), text: value })
      : await api.put(`/api/projects/${projectId}`, { [editing]: value });
    if (!r.ok) { setError(r.error); return; }
    if (editing === "folder" && value) onUseFolder(value);
    setEditing(""); setDraft("");
    void load();
  };
  const edit = (what: "folder" | "instructions" | "note", start = "") => { setEditing(what); setDraft(start); setError(""); };

  if (!open) {
    return (
      <button type="button" className="pj-bar" onClick={() => setOpen(true)} aria-expanded={false}>
        <span aria-hidden="true">▣</span> <b>{project.name}</b>
        <span className="pj-bar__meta">{threads.length} threads · {docs.length + project.artifacts.length} files{project.folder ? ` · ${project.folder.split(/[\\/]/).filter(Boolean).pop()}` : ""}</span>
        <span aria-hidden="true" className="ov-chev">⌄</span>
      </button>
    );
  }

  const rows: { icon: string; label: string; where: string; action?: () => void; actionLabel?: string }[] = [
    { icon: "▭", label: project.folder ? project.folder.split(/[\\/]/).filter(Boolean).pop() || project.folder : "No folder yet",
      where: project.folder ? "Project folder on this PC" : "Link a folder", action: () => edit("folder", project.folder || ""), actionLabel: project.folder ? "Change" : "Link" },
    { icon: "☁", label: `${(project.drives ?? []).length} ${(project.drives ?? []).length === 1 ? "drive" : "drives"} · browse and add files`,
      where: "Folders the main chat may open", action: () => setPanel(panel === "files" ? "" : "files"), actionLabel: panel === "files" ? "Close" : "Open" },
    { icon: "✎", label: project.instructions ? "Instructions" : "No instructions yet", where: "Every chat and thread here follows them",
      action: () => edit("instructions", project.instructions || ""), actionLabel: project.instructions ? "Edit" : "Add" },
    { icon: "▤", label: `${docs.length} knowledge ${docs.length === 1 ? "file" : "files"} · ${project.artifacts.length} in the Library`, where: "What threads draw on",
      action: () => edit("note"), actionLabel: "Add a note" },
    { icon: "◌", label: `${threads.length} ${threads.length === 1 ? "thread" : "threads"}${board?.needs_you ? ` · ${board.needs_you} need you` : ""}`,
      where: "In the Threads panel", action: onShowThreads, actionLabel: "Open" },
    { icon: "⚖", label: balance ? `${balance.counts.free} free · ${balance.counts.busy} busy · ${balance.counts.waiting} waiting · ${balance.counts.full} full` : "No threads yet",
      where: "The main chat balances work across them" },
    { icon: "⇄", label: helpers.length || project.tabs.length ? `${helpers.length} helpers · ${project.tabs.length} tabs` : "No connections yet",
      where: "Helpers, tabs and the Library", action: () => setPanel(panel === "setup" ? "" : "setup"), actionLabel: panel === "setup" ? "Close" : "Setup" },
  ];

  return (
    <section className="pj-home" aria-label={`Project ${project.name}`}>
      <header className="pj-home__head">
        <div>
          <h2>Hi{name ? ` ${name}` : ""} <span aria-hidden="true">👋</span><br />let me show you around</h2>
          <p>{project.goal || `${project.name}: one chat for the whole project. Ask for anything and the work splits into threads.`}</p>
        </div>
        <span className="pj-home__tools">
          <button type="button" className={`ov-close${project.starred ? " is-on" : ""}`} aria-pressed={Boolean(project.starred)}
            onClick={() => void api.put(`/api/projects/${projectId}`, { starred: !project.starred }).then(() => load())}
            aria-label={project.starred ? "Unstar this project" : "Star this project"} title={project.starred ? "Unstar" : "Star: keep at the top"}>{project.starred ? "★" : "☆"}</button>
          {!empty && <button type="button" className="ov-close" onClick={() => setOpen(false)} aria-label="Fold the project home" title="Fold">⌃</button>}
        </span>
      </header>
      <div className="pj-card">
        <h3>Your context</h3>
        <ul>
          {rows.map((r) => (
            <li key={r.where}>
              <span className="pj-icon" aria-hidden="true">{r.icon}</span>
              <span className="pj-label">{r.label}</span>
              <span className="pj-where">{r.where}</span>
              {r.action && <button type="button" className="pj-act" onClick={r.action}>{r.actionLabel}</button>}
            </li>
          ))}
        </ul>
        {editing && (
          <form className="ov-lib-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            {editing === "folder"
              ? <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="C:\Users\you\Desktop\My project" aria-label="Project folder" />
              : <textarea autoFocus rows={editing === "instructions" ? 6 : 4} value={draft} onChange={(e) => setDraft(e.target.value)}
                  aria-label={editing === "note" ? "Knowledge note" : "Instructions"}
                  placeholder={editing === "note" ? "First line is the title" : "How every chat in this project should work"} />}
            {error && <p className="ov-error">{error}</p>}
            <span><button type="submit" className="btn btn-secondary">Save</button>
              <button type="button" className="btn" onClick={() => setEditing("")}>Cancel</button></span>
          </form>
        )}
      </div>
      {panel === "files" && <ProjectFiles projectId={projectId} folder={project.folder || ""} drives={project.drives ?? []} onChanged={() => void load()} />}
      {panel === "setup" && (
        <Suspense fallback={<p className="pj-hint">Opening the setup…</p>}>
          <ProjectSetup projectId={projectId} onChanged={() => void load()} onDeleted={() => setPanel("")} />
        </Suspense>
      )}
      {threads.length > 0 && (
        <div className="pj-card">
          <h3>Your recent threads</h3>
          <ul>
            {threads.slice(0, 5).map((t) => (
              <li key={t.id}>
                <button type="button" className={`ov-row is-${t.status === "needs_you" ? "waiting" : t.status}`} onClick={() => onOpenChat(t.chat_id)}>
                  <span className="ov-dot" aria-hidden="true" />
                  <span className="ov-text"><b>{t.title}</b><span className="ov-line">{t.line || t.status_label}</span></span>
                  <span className="ov-age">{ago(t.updated * 1000)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="pj-hint">I'm happy to help with whatever you need. Just ask and I'll kick off a thread for you.</p>
    </section>
  );
}
