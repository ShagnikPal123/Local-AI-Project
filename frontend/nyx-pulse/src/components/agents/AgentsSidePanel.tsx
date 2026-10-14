/** The agents side panel (owner request, 2026-10-14).
 *
 * "Under skills and agents for the button next to the chat box they can open a side panel where they can drag and drop
 * agents into any chat on the left panel, drag into this chat, drag into a project." It replaces the Second Brain's
 * Core view as the place agents were dragged from, so the Second Brain could go.
 *
 * Three drop targets, all using the existing agent drag format (`application/x-nyx-agent`, as AgentBoxes reads it):
 *   • a chat in the left rail — that chat opens and the agent box sheet opens for it;
 *   • this chat (the panel's own zone, or anywhere on the conversation) — the box sheet opens for the current chat;
 *   • a project — the agent joins the project's sub-agents (`/api/projects/{id}/members`), what Projects builds on next.
 * Nothing runs on drop: the box sheet still asks what each copy should do, so a stray drag costs nothing.
 */

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";
import { startItemDrag } from "../../state/dragItems";
import { DispatchSheet, useRoster } from "./AgentBoxes";
import "./agents.css";

export const AGENTS_PANEL_EVENT = "ichos:agents-panel";
const AGENT_DRAG = "application/x-nyx-agent";

/** Opens (or closes) the panel from anywhere, e.g. the ✦ menu beside the chat box. */
export function toggleAgentsPanel(): void {
  window.dispatchEvent(new CustomEvent(AGENTS_PANEL_EVENT));
}

interface ProjectRow { id: string; name: string; members: Record<string, string[]> }

/** The same / command the chat understands for an agent (SubAgentsPanel's slug). */
const slugOf = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32);

function activeChat(): string {
  try {
    const id = localStorage.getItem("nyx.chat.active") || "";
    return id === "default" ? "" : id;
  } catch { return ""; }
}

/** Which chat a drop landed on: a rail row names its chat; the conversation itself is the current chat. */
function chatUnder(target: EventTarget | null): { chatId: string; title: string } | null {
  const el = target instanceof Element ? target : null;
  const row = el?.closest<HTMLElement>("[data-chat-id]");
  if (row?.dataset.chatId) return { chatId: row.dataset.chatId, title: row.dataset.chatTitle || "that chat" };
  if (el?.closest(".chat-shell__chat")) return { chatId: activeChat(), title: "this chat" };
  return null;
}

export function AgentsSidePanel() {
  const [open, setOpen] = useState(false);
  const roster = useRoster();
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [sheet, setSheet] = useState<{ agent: string; chatId: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);

  useEffect(() => {
    const onToggle = () => setOpen((v) => !v);
    window.addEventListener(AGENTS_PANEL_EVENT, onToggle);
    return () => window.removeEventListener(AGENTS_PANEL_EVENT, onToggle);
  }, []);

  const loadProjects = useCallback(async () => {
    const result = await api.get<{ projects: ProjectRow[] }>("/api/projects");
    if (result.ok) setProjects(result.data.projects);
  }, []);
  useEffect(() => { if (open) void loadProjects(); }, [open, loadProjects]);

  const toChat = useCallback((agent: string, chatId: string) => {
    // Another chat: switch to it first, so the boxes' card shows up where they report.
    if (chatId && chatId !== activeChat()) window.dispatchEvent(new CustomEvent("nyx:open-chat", { detail: { chatId } }));
    setSheet({ agent, chatId });
  }, []);

  // While the panel is open, the rail's chats and the conversation take agent drops too. Bubble phase, and only when
  // nothing nearer took the drop (the box editor handles its own), so existing drops keep working.
  useEffect(() => {
    if (!open) return;
    const onOver = (e: DragEvent) => {
      if (e.defaultPrevented || !e.dataTransfer?.types.includes(AGENT_DRAG)) return;
      if (chatUnder(e.target)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }
    };
    const onDrop = (e: DragEvent) => {
      if (e.defaultPrevented) return;
      const agent = e.dataTransfer?.getData(AGENT_DRAG);
      const chat = agent ? chatUnder(e.target) : null;
      if (!agent || !chat) return;
      e.preventDefault();
      toChat(agent, chat.chatId);
    };
    document.addEventListener("dragover", onOver);
    document.addEventListener("drop", onDrop);
    return () => { document.removeEventListener("dragover", onOver); document.removeEventListener("drop", onDrop); };
  }, [open, toChat]);

  async function toProject(agent: string, project: ProjectRow) {
    if ((project.members.subagents ?? []).includes(agent)) { pushToast(`${agent} is already on ${project.name}.`, "ok"); return; }
    const result = await api.post<{ project: ProjectRow }>(`/api/projects/${encodeURIComponent(project.id)}/members`,
      { kind: "subagents", member: agent, on: true });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setProjects((list) => list.map((p) => (p.id === project.id ? { ...p, members: result.data.project.members } : p)));
    pushToast(`${agent} joined ${project.name}.`, "ok");
  }

  async function offProject(agent: string, project: ProjectRow) {
    const result = await api.post<{ project: ProjectRow }>(`/api/projects/${encodeURIComponent(project.id)}/members`,
      { kind: "subagents", member: agent, on: false });
    if (result.ok) setProjects((list) => list.map((p) => (p.id === project.id ? { ...p, members: result.data.project.members } : p)));
  }

  /** Drop-zone props: highlight while an agent is over it, hand the agent to `onAgent` on drop. */
  const zone = (key: string, onAgent: (agent: string) => void) => ({
    className: `agents-side__zone${over === key ? " is-over" : ""}`,
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes(AGENT_DRAG)) { e.preventDefault(); setOver(key); } },
    onDragLeave: () => setOver((k) => (k === key ? null : k)),
    onDrop: (e: React.DragEvent) => {
      const agent = e.dataTransfer.getData(AGENT_DRAG);
      setOver(null);
      if (!agent) return;
      e.preventDefault();
      onAgent(agent);
    },
  });

  const panel = open && (
    <aside className="agents-side" aria-label="Agents">
      <header className="agents-side__head">
        <h2>Agents</h2>
        <button type="button" className="box__remove" onClick={() => setOpen(false)} aria-label="Close the agents panel">✕</button>
      </header>
      <p className="agents-side__hint">Drag an agent onto a chat in the left list, onto this chat, or onto a project.</p>
      <ul className="agents-side__list">
        {roster.map((a) => (
          <li key={a.name} className="agents-side__agent" draggable
            onDragStart={(e) => {
              startItemDrag(e, { kind: "agent", id: a.name, label: a.name });
              e.dataTransfer.setData(AGENT_DRAG, a.name);
              e.dataTransfer.effectAllowed = "copy";
            }}
            title={`${a.goal}\n/${slugOf(a.name)}`}>
            <span className="core__grip" aria-hidden="true">⋮⋮</span>
            <span className="box__emoji" aria-hidden="true">{a.emoji || "🤖"}</span>
            <span className="agents-side__who"><b>{a.name}</b><span>{a.goal}</span></span>
            <button type="button" className="chat-inline" onClick={() => toChat(a.name, activeChat())} aria-label={`Put ${a.name} on this chat`}>Use</button>
          </li>
        ))}
        {roster.length === 0 && <li className="agents-side__empty">No agents yet. Make one in the Sub-agents tab.</li>}
      </ul>

      <div className="agents-side__caption">Drop here</div>
      <div {...zone("chat", (agent) => toChat(agent, activeChat()))}>
        <span aria-hidden="true">⤓</span> This chat
      </div>

      <div className="agents-side__caption">Projects</div>
      {projects.map((p) => (
        <div key={p.id} {...zone(`p:${p.id}`, (agent) => void toProject(agent, p))}>
          <b>📁 {p.name}</b>
          <span className="agents-side__members">
            {(p.members.subagents ?? []).map((m) => (
              <button key={m} type="button" className="chip" title="Take off the project" onClick={() => void offProject(m, p)}>{m} ✕</button>
            ))}
            {(p.members.subagents ?? []).length === 0 && <span className="muted">drop agents here</span>}
          </span>
        </div>
      ))}
      {projects.length === 0 && <p className="agents-side__empty">No projects yet. Make one in Projects.</p>}
    </aside>
  );

  return (
    <>
      {panel && createPortal(panel, document.body)}
      {sheet && (
        <DispatchSheet text={`/${slugOf(sheet.agent)}`} chatId={sheet.chatId} onClose={() => setSheet(null)}
          onStarted={(d) => pushToast(`${d.instances.length} agent${d.instances.length === 1 ? "" : "s"} started — results go to the chat.`, "ok")} />
      )}
    </>
  );
}
