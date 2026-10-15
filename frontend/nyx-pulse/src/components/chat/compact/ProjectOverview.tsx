/** The Overview panel inside a project (owner, 2026-10-15): "that is where overview is mainly meant to be used as it is
 *  for a big project which has a main chat where users type in and threads the main chat creates and communicates with".
 *
 *  • **ProjectThreads**: the project's name and how its threads stand, the main chat pinned on top, then the threads
 *    the main chat started, grouped Needs you · Working · Idle · Resolved. Read live from /api/commander, refreshed every
 *    few seconds while the window is visible.
 *  • **ProjectLibrary**: what the project holds: its knowledge files, its Library (results its threads filed and
 *    artifacts put on it) and its folder and drives (ProjectFiles). */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api";
import { ago } from "./OverviewPanel";
import { ProjectFiles } from "./ProjectFiles";

interface Thread { id: string; chat_id: string; title: string; status: string; line: string; status_label: string; updated: number; job?: string }
interface Board { groups: { id: string; label: string; threads: Thread[] }[]; total: number; needs_you: number; working: number }
interface Project {
  id: string; name: string; goal: string; folder?: string; drives?: string[];
  artifacts: { id: string; title: string; kind: string; note: string; ref: string; created: number }[];
}

function useProject(projectId: string) {
  const [project, setProject] = useState<Project | null>(null);
  const load = useCallback(async () => {
    const r = await api.get<{ project: Project }>(`/api/projects/${projectId}`);
    if (r.ok) setProject(r.data.project);
  }, [projectId]);
  useEffect(() => { setProject(null); void load(); }, [load]);
  return { project, reload: load };
}

export function ProjectThreads({ projectId, mainChatId, activeId, onOpen, filter }: {
  projectId: string; mainChatId: string; activeId: string; onOpen: (chatId: string) => void; filter: string;
}) {
  const { project } = useProject(projectId);
  const [board, setBoard] = useState<Board | null>(null);
  const [closed, setClosed] = useState<Record<string, boolean>>({ resolved: true });

  useEffect(() => {
    let alive = true;
    const read = async () => {
      if (document.hidden) return;
      const r = await api.get<{ board: Board }>(`/api/commander?project_id=${encodeURIComponent(projectId)}`);
      if (alive && r.ok) setBoard(r.data.board);
    };
    void read();
    const timer = window.setInterval(() => void read(), 5000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [projectId]);

  const wanted = filter.trim().toLowerCase();
  const groups = (board?.groups ?? [])
    .map((g) => ({ ...g, threads: g.threads.filter((t) => !wanted || `${t.title} ${t.line}`.toLowerCase().includes(wanted)) }))
    .filter((g) => g.threads.length || g.id === "needs_you");
  const waiting = board?.needs_you ?? 0;
  const working = board?.working ?? 0;
  const group = (id: string) => (id === "needs_you" ? "waiting" : id);

  return (
    <div className="ov-threads">
      <header className="ov-welcome">
        <div>
          <h2>{project?.name ?? "Project"}</h2>
          <p>{waiting ? `${waiting} ${waiting === 1 ? "thread is" : "threads are"} waiting on you.`
            : working ? `${working} ${working === 1 ? "thread is" : "threads are"} working. I'll ping you.`
            : board?.total ? "All quiet. Ask in the main chat and it hands the work out." : "No threads yet. Ask in the main chat and it starts them."}</p>
        </div>
      </header>
      <ul className="ov-list">
        <li>
          <button type="button" className={`ov-row is-pinned${mainChatId === activeId ? " is-open" : ""}`} onClick={() => onOpen(mainChatId)}
            disabled={!mainChatId}>
            <span className="ov-dot" aria-hidden="true" />
            <span className="ov-text"><b>Main chat</b><span className="ov-line">Where you type; it starts and steers the threads</span></span>
          </button>
        </li>
      </ul>
      {groups.map((g) => (
        <section key={g.id} className="ov-group">
          <button type="button" className="ov-group__head" aria-expanded={!closed[g.id]}
            onClick={() => setClosed((c) => ({ ...c, [g.id]: !c[g.id] }))}>
            <span aria-hidden="true" className="ov-chev">{closed[g.id] ? "›" : "⌄"}</span>
            {g.id === "needs_you" ? "Waiting on you" : g.label} <span className="ov-n">{g.threads.length}</span>
          </button>
          {!closed[g.id] && g.id === "needs_you" && g.threads.length === 0 && !wanted && (
            <p className="ov-empty">Decisions, reviews, and permission requests from this project's threads.</p>
          )}
          {!closed[g.id] && g.threads.length > 0 && (
            <ul className="ov-list">
              {[...g.threads].sort((a, b) => b.updated - a.updated).map((t) => (
                <li key={t.id}>
                  <button type="button" className={`ov-row is-${group(t.status)}${t.chat_id === activeId ? " is-open" : ""}`}
                    onClick={() => onOpen(t.chat_id)} aria-label={`${t.title}: ${t.status_label}, ${t.line}`}>
                    <span className="ov-dot" aria-hidden="true" />
                    <span className="ov-text">
                      <b>{t.title}</b>
                      <span className="ov-line">{t.job && <em>{t.job} · </em>}{t.line || t.status_label}</span>
                    </span>
                    <span className="ov-age">{ago(t.updated * 1000)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

export function ProjectLibrary({ projectId, onOpenChat }: { projectId: string; onOpenChat: (chatId: string) => void }) {
  const { project, reload } = useProject(projectId);
  const [docs, setDocs] = useState<{ id: string; title: string }[]>([]);
  const [error, setError] = useState("");
  const loadDocs = useCallback(async () => {
    const r = await api.get<{ docs: { id: string; title: string }[] }>(`/api/commander/projects/${projectId}/knowledge`);
    if (r.ok) setDocs(r.data.docs);
  }, [projectId]);
  useEffect(() => { void loadDocs(); }, [loadDocs]);
  if (!project) return null;

  const openItem = async (id: string) => {
    setError("");
    const r = await api.post<{ chat_id: string }>(`/api/artifacts/${id}/chat`, {});
    if (r.ok) onOpenChat(r.data.chat_id); else setError(r.error);
  };

  return (
    <div className="ov-library">
      {error && <p className="ov-error" role="alert">{error}</p>}
      <section className="ov-group">
        <h3 className="ov-group__head">Knowledge <span className="ov-n">{docs.length}</span></h3>
        {docs.length === 0 && <p className="ov-empty">Files and notes added here go into every thread's brief.</p>}
        <ul className="ov-list">
          {docs.map((d) => <li key={d.id} className="ov-row is-idle"><span className="ov-text"><b>{d.title}</b></span></li>)}
        </ul>
      </section>
      <section className="ov-group">
        <h3 className="ov-group__head">Library <span className="ov-n">{project.artifacts.length}</span></h3>
        {project.artifacts.length === 0 && <p className="ov-empty">A thread's result lands here when it finishes.</p>}
        <ul className="ov-list">
          {project.artifacts.slice(0, 40).map((a) => (
            <li key={a.id}>
              <button type="button" className="ov-row is-idle" onClick={() => void openItem(a.id)} title={a.note.slice(0, 300)}>
                <span className="ov-text"><b>{a.title}</b><span className="ov-line">{a.ref.startsWith("th-") ? "from a thread" : a.kind}</span></span>
                <span className="ov-age">{ago(a.created * 1000)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <ProjectFiles projectId={projectId} folder={project.folder || ""} drives={project.drives ?? []}
        onChanged={() => { void reload(); void loadDocs(); }} />
    </div>
  );
}
