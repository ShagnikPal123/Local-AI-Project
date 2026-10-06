/** One office, open: the floor, the two chats, the section bars, and everything that controls them. */

import { useCallback, useMemo, useState } from "react";
import { Floor } from "./Floor";
import { MainChat, TargetChat } from "./Chats";
import { SectionBar } from "./SectionBar";
import { SectionDrawer } from "./SectionDrawer";
import { Sidebar } from "./Sidebar";
import { AgentCard, HiringList } from "./Pieces";
import { OutputBox } from "./OutputBox";
import { officeApi, EMPTY_SELECTION, type Selection } from "./officeApi";
import type { LibraryTree, OfficeSnapshot } from "./types";
import type { OfficeLive } from "./useOffice";

interface OfficeViewProps {
  live: OfficeLive;
  snapshot: OfficeSnapshot;
  tree: LibraryTree | null;
  onLobby: () => void;
  onOpenOffice: (id: string) => void;
  onNewOffice: (parent: string) => void;
  onError: (message: string) => void;
}

function toggle(list: string[], id: string, additive: boolean): string[] {
  if (!additive) return list.length === 1 && list[0] === id ? [] : [id];
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export function OfficeView({ live, snapshot, tree, onLobby, onOpenOffice, onNewOffice, onError }: OfficeViewProps) {
  const office = snapshot.office;
  const [selection, setSelection] = useState<Selection>(EMPTY_SELECTION);
  const [openSection, setOpenSection] = useState("");
  const [openAgent, setOpenAgent] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const [sending, setSending] = useState(false);
  const [aiming, setAiming] = useState(false);

  const running = office.status === "running" || office.status === "paused";
  const busy = office.counts.working;

  const autoDecisions = Boolean(office.settings?.auto_decisions);
  const toggleAuto = useCallback(async () => {
    const result = await officeApi.options(office.id, { auto_decisions: !autoDecisions });
    if (result.ok) live.apply(result.data);
    else onError(result.error);
  }, [office.id, autoDecisions, live, onError]);

  const control = useCallback(async (action: "pause" | "resume" | "halt",
                                     scope: "office" | "section" | "agent" = "office", id = "") => {
    const result = await officeApi.control(office.id, action, scope, id);
    if (result.ok) live.apply(result.data);
    else onError(result.error);
  }, [office.id, live, onError]);

  const sendMain = useCallback(async (text: string) => {
    setSending(true);
    const result = await officeApi.chat(office.id, text);
    setSending(false);
    if (result.ok) live.apply(result.data.snapshot);
    else onError(result.error);
  }, [office.id, live, onError]);

  const sendTarget = useCallback(async (text: string) => {
    setAiming(true);
    const result = await officeApi.say(office.id, text, selection, openSection);
    setAiming(false);
    if (!result.ok) onError(result.error);
    else void live.reload();
  }, [office.id, selection, openSection, live, onError]);

  const section = openSection ? live.sectionsById[openSection] : undefined;
  const agent = openAgent ? live.agentsById[openAgent] : undefined;
  const drawerAgents = useMemo(
    () => snapshot.agents.filter((a) => a.section_id === openSection).sort((a, b) => a.desk - b.desk),
    [snapshot.agents, openSection]);

  return (
    <div className={`ofc-office${sidebar ? " has-side" : ""}`}>
      <header className="ofc-top">
        <button className="ofc-icon" onClick={() => setSidebar((open) => !open)}
                aria-label="Offices, folders and files" title="Offices, folders and files">☰</button>
        <button className="ofc-link" onClick={onLobby}>All offices</button>
        <h1>{office.name}</h1>
        <span className={`ofc-pill is-${office.status}`}>
          <i />{office.status === "running" ? (office.phase || "working")
            : office.status === "paused" ? "paused" : office.status === "halted" ? "halted" : "ready"}
        </span>
        <span className="ofc-top__counts" title={office.capacity_detail?.reason}>
          {office.counts.agents} agents{busy ? ` · ${busy} working` : ""} · {office.counts.sections} sections ·
          {" "}{office.counts.tasks_done}/{office.counts.tasks} tasks
        </span>
        {snapshot.focus?.held && (
          <span className="ofc-pill is-focus" title={snapshot.focus.note || "Nyx's background work is paused"}>
            <i />only this office
          </span>
        )}
        <div className="ofc-top__actions">
          {/* U42: "a button allows for auto decisions so the ai knows it needs to really give an output". */}
          <button className={`ofc-btn ofc-btn--small ofc-auto${autoDecisions ? " is-on" : ""}`} aria-pressed={autoDecisions}
                  onClick={() => void toggleAuto()}
                  title={autoDecisions ? "Auto decisions is on: the office decides everything and delivers the real result"
                    : "Turn on Auto decisions: the office decides open questions itself and delivers the real result, not a plan"}>
            Auto decisions{autoDecisions ? " · on" : ""}
          </button>
          {running && office.status !== "paused" && (
            <button className="ofc-btn ofc-btn--small" onClick={() => void control("pause")}>Pause</button>
          )}
          {office.status === "paused" && (
            <button className="ofc-btn ofc-btn--small" onClick={() => void control("resume")}>Resume</button>
          )}
          {running && (
            <button className="ofc-btn ofc-btn--small ofc-btn--risk" onClick={() => void control("halt")}>Halt</button>
          )}
        </div>
      </header>

      <SectionBar variant="top" sections={snapshot.sections} agents={snapshot.agents} tasks={snapshot.tasks}
                  roles={live.rolesById} selectedSections={selection.sections} selectedRoles={selection.roles}
                  openSection={openSection}
                  onToggleSection={(id, additive) =>
                    setSelection((s) => ({ ...s, sections: toggle(s.sections, id, additive) }))}
                  onOpenSection={(id) => setOpenSection((current) => (current === id ? "" : id))} />

      <div className="ofc-body">
        {sidebar && (
          <Sidebar tree={tree} officeId={office.id} onOpenOffice={onOpenOffice} onLobby={onLobby}
                   onNewOffice={onNewOffice} onClose={() => setSidebar(false)}
                   onReveal={(id) => void officeApi.reveal(id)} />
        )}

        <div className="ofc-stage">
          <Floor sections={snapshot.sections} agents={snapshot.agents} roles={live.rolesById} talks={live.talks}
                 selectedSections={selection.sections} selectedAgents={selection.agents}
                 gatekeeperId={office.gatekeeper_id}
                 onPickAgent={(id, additive) =>
                   setSelection((s) => ({ ...s, agents: toggle(s.agents, id, additive) }))}
                 onOpenSection={(id) => setOpenSection((current) => (current === id ? "" : id))}
                 onToggleSection={(id, additive) =>
                   setSelection((s) => ({ ...s, sections: toggle(s.sections, id, additive) }))} />

          {section && (
            <SectionDrawer section={section} agents={drawerAgents} tasks={snapshot.tasks} roles={live.rolesById}
                           manager={live.agentsById[section.manager_id]} selectedAgents={selection.agents}
                           onPickAgent={(id) => setSelection((s) => ({ ...s, agents: toggle(s.agents, id, true) }))}
                           onPickMany={(ids, on) => setSelection((s) => ({
                             ...s, agents: on ? [...new Set([...s.agents, ...ids])] : s.agents.filter((a) => !ids.includes(a)),
                           }))}
                           onControl={(action, scope, id) => void control(action, scope, id)}
                           onOpenAgent={setOpenAgent}
                           onClose={() => setOpenSection("")} />
          )}

          {agent && (
            <AgentCard agent={agent} role={live.rolesById[agent.role]} section={live.sectionsById[agent.section_id]}
                       task={snapshot.tasks.find((t) => t.id === agent.task_id)}
                       onControl={(action, id) => void control(action, "agent", id)}
                       onTalkTo={(id) => { setSelection({ sections: [], roles: [], agents: [id] }); setOpenAgent(""); }}
                       onClose={() => setOpenAgent("")} />
          )}
        </div>

        <div className="ofc-talkcol">
          <MainChat messages={snapshot.chat} job={snapshot.job} phase={office.phase} running={running}
                    onSend={sendMain} sending={sending} />
          <OutputBox officeId={office.id} outputs={snapshot.outputs ?? []} onError={onError} />
          <TargetChat officeId={office.id} messages={snapshot.thread} selection={selection}
                      sections={live.sectionsById} agents={live.agentsById} roles={live.rolesById}
                      focusSection={openSection} onSend={sendTarget} sending={aiming}
                      onDropChip={(kind, id) => setSelection((s) => ({ ...s, [kind]: s[kind].filter((x) => x !== id) }))}
                      onClear={() => setSelection(EMPTY_SELECTION)} />
          <HiringList hires={snapshot.hires} staffing={snapshot.staffing ?? []}
                      boardName={live.agentsById[office.gatekeeper_id]?.name ?? ""} />
          {office.gatekeeper_reason && !office.gatekeeper_id && (
            <p className="ofc-muted ofc-note">{office.gatekeeper_reason}</p>
          )}
        </div>
      </div>

      <SectionBar variant="dock" sections={snapshot.sections} agents={snapshot.agents} tasks={snapshot.tasks}
                  roles={live.rolesById} selectedSections={selection.sections} selectedRoles={selection.roles}
                  openSection={openSection}
                  onToggleSection={(id, additive) =>
                    setSelection((s) => ({ ...s, sections: toggle(s.sections, id, additive) }))}
                  onOpenSection={(id) => setOpenSection((current) => (current === id ? "" : id))}
                  onToggleRole={(id, additive) =>
                    setSelection((s) => ({ ...s, roles: toggle(s.roles, id, additive) }))} />
    </div>
  );
}
