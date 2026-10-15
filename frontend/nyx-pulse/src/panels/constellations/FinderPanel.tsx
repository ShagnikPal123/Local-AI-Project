/** Constellations: every project and artifact, sorted for you, and each one opens in the main chat.
 *
 *  The owner (2026-10-15): projects no longer open as a tab of their own; they live in the chat. "The other tab for
 *  constellations can auto sort the projects and artifacts and make sure it is easy for the user to find, which it then
 *  opens in main chat."
 *
 *  • **Smart** (the default) sorts into groups: Needs you, Starred, This week, then the other projects, then artifacts
 *    by kind (Plans, Code, Designs…). **Recent** is one list newest first; **A–Z** is by name.
 *  • A search box and a Projects / Artifacts filter narrow it.
 *  • Opening a project opens its main chat; opening an artifact opens the chat it came from (or one made for it). */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import "./constellations.css";

interface Artifact { id: string; title: string; kind: string; note: string; project_id: string; ref: string; created: number; updated?: number }
interface Project { id: string; name: string; goal: string; starred?: boolean; updated?: number; created?: number; artifacts: Artifact[] }
interface TaskCount { done: number; total: number; needs_you: number }

interface Item {
  key: string; kind: "project" | "artifact"; id: string; title: string; sub: string; when: number;
  starred: boolean; needsYou: boolean; group: string;
  /** An artifact's kind (plan, code…); empty for a project. */
  artKind: string;
}

type Sort = "smart" | "recent" | "az";
type Show = "all" | "project" | "artifact";

const WEEK = 7 * 86_400;
const KIND_GROUPS: Record<string, string> = {
  plan: "Plans", code: "Code", design: "Designs", document: "Documents", image: "Images", idea: "Ideas", other: "Other things",
};
const SMART_ORDER = ["Needs you", "Starred", "This week", "Projects", "Plans", "Code", "Designs", "Documents", "Images", "Ideas", "Other things"];

/** Open a chat in the main chat (the Chat tab). */
export function openInChat(chatId: string): void {
  try { sessionStorage.setItem("nyx.chat.open", chatId); } catch { /* not kept */ }
  window.dispatchEvent(new CustomEvent("nyx:open-chat", { detail: { chatId } }));
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "nyx" } }));
}

function ago(seconds: number): string {
  if (!seconds) return "";
  const s = Date.now() / 1000 - seconds;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86_400)}d ago`;
}

/** The smart group an item belongs to. */
export function smartGroup(item: Omit<Item, "group">, now: number): string {
  if (item.needsYou) return "Needs you";
  if (item.starred) return "Starred";
  if (item.when && now - item.when < WEEK) return "This week";
  return item.kind === "project" ? "Projects" : KIND_GROUPS[item.artKind] ?? "Other things";
}

export function FinderPanel() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [tasks, setTasks] = useState<Record<string, TaskCount>>({});
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>(() => { try { return (localStorage.getItem("ichos.find.sort") as Sort) || "smart"; } catch { return "smart"; } });
  const [show, setShow] = useState<Show>("all");
  const [error, setError] = useState("");
  const [opening, setOpening] = useState("");

  const load = useCallback(async () => {
    const [p, a, b] = await Promise.all([
      api.get<{ projects: Project[] }>("/api/projects"),
      api.get<{ artifacts: Artifact[] }>("/api/artifacts"),
      api.get<{ board: { by_project: Record<string, TaskCount> } }>("/api/commander"),
    ]);
    if (p.ok) setProjects(p.data.projects); else setError(p.error);
    if (a.ok) setArtifacts(a.data.artifacts);
    if (b.ok) setTasks(b.data.board.by_project ?? {});
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { try { localStorage.setItem("ichos.find.sort", sort); } catch { /* not kept */ } }, [sort]);

  const items = useMemo<Item[]>(() => {
    const now = Date.now() / 1000;
    const names = new Map(projects.map((p) => [p.id, p.name]));
    const rows: Omit<Item, "group">[] = [
      ...projects.map((p) => {
        const t = tasks[p.id];
        return {
          key: `p:${p.id}`, kind: "project" as const, artKind: "", id: p.id, title: p.name, starred: Boolean(p.starred), needsYou: Boolean(t?.needs_you),
          when: p.updated || p.created || 0,
          sub: [t?.total ? `Tasks ${t.done}/${t.total}` : "", `${p.artifacts.length} in the Library`, p.goal].filter(Boolean).join(" · "),
        };
      }),
      ...artifacts.map((a) => ({
        key: `a:${a.id}`, kind: "artifact" as const, artKind: a.kind, id: a.id, title: a.title, starred: false, needsYou: false,
        when: a.updated || a.created || 0,
        sub: [a.kind, a.project_id ? names.get(a.project_id) ?? "" : "No project", a.ref.startsWith("th-") ? "from a thread" : ""].filter(Boolean).join(" · "),
      })),
    ];
    return rows.map((r) => ({ ...r, group: smartGroup(r, now) }));
  }, [projects, artifacts, tasks]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const kept = items.filter((i) => (show === "all" || i.kind === show) && (!q || `${i.title} ${i.sub}`.toLowerCase().includes(q)));
    if (sort === "az") return kept.sort((a, b) => a.title.localeCompare(b.title));
    return kept.sort((a, b) => b.when - a.when);
  }, [items, query, show, sort]);

  const groups = useMemo(() => {
    if (sort !== "smart") return [{ name: sort === "az" ? "A–Z" : "Newest first", rows: shown }];
    return SMART_ORDER.map((name) => ({ name, rows: shown.filter((i) => i.group === name) })).filter((g) => g.rows.length);
  }, [shown, sort]);

  const open = async (item: Item) => {
    setError(""); setOpening(item.key);
    const r = item.kind === "project"
      ? await api.post<{ chat_id: string }>(`/api/commander/projects/${item.id}/chat`, {})
      : await api.post<{ chat_id: string }>(`/api/artifacts/${item.id}/chat`, {});
    setOpening("");
    if (r.ok) openInChat(r.data.chat_id); else setError(r.error);
  };

  return (
    <div className="cx cx-find">
      <header className="cx-head"><h1>Constellations<small>Projects and artifacts</small></h1>
        <p>Everything you and Ichos made, sorted for you. Open one and it opens in the main chat.</p></header>
      <div className="cx-find__bar">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a project or artifact" aria-label="Find" />
        <div className="cx-row" role="group" aria-label="Show">
          {(["all", "project", "artifact"] as Show[]).map((s) => (
            <button key={s} type="button" className={`cx-chip ${show === s ? "is-on" : ""}`} aria-pressed={show === s} onClick={() => setShow(s)}>
              {s === "all" ? "All" : s === "project" ? "Projects" : "Artifacts"}
            </button>
          ))}
        </div>
        <div className="cx-row" role="group" aria-label="Sort">
          {(["smart", "recent", "az"] as Sort[]).map((s) => (
            <button key={s} type="button" className={`cx-chip ${sort === s ? "is-on" : ""}`} aria-pressed={sort === s} onClick={() => setSort(s)}>
              {s === "smart" ? "Smart" : s === "recent" ? "Recent" : "A–Z"}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="cx-error" role="alert">{error}</p>}
      {groups.map((g) => (
        <section key={g.name} className="cx-find__group" aria-label={g.name}>
          <h2>{g.name} <span className="cx-muted">{g.rows.length}</span></h2>
          <ul>
            {g.rows.map((i) => (
              <li key={i.key}>
                <button type="button" className="cx-find__row" onClick={() => void open(i)} disabled={opening === i.key}>
                  <span className="cx-find__mark" aria-hidden="true">{i.kind === "project" ? (i.starred ? "★" : "▣") : "◆"}</span>
                  <span className="cx-find__text"><b>{i.title}</b><span className="cx-muted">{i.sub}</span></span>
                  {i.needsYou && <span className="cx-needs">● Needs you</span>}
                  <span className="cx-muted cx-find__when">{opening === i.key ? "Opening…" : ago(i.when)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {groups.length === 0 && (
        <p className="cx-muted">{items.length ? "Nothing matches that." : "No projects or artifacts yet. Make a project from the chat list with ＋ beside Projects."}</p>
      )}
    </div>
  );
}
