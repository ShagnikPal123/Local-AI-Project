/** The boxes for the sections — the same idea at the top of the office and in the dock at the bottom.
 *
 * The owner asked for both: *"a section on top I can scroll and click 1 or more boxes which represent sections,
 * I can talk double click a section and deselect or select a single or multiple agents of that group"*, and
 * *"On the bottom also add the same type of box system … it can also be used to select and send certain
 * messages to a section or bot or certain types of bots."*
 *
 * So one component, two shapes. The dock adds the kinds of agent, because that is the other way the owner
 * picks a crowd ("coder agents in every group", "optimizers of these groups").
 */

import type { OfficeAgent, OfficeRole, OfficeSection, OfficeTask } from "./types";

interface SectionBarProps {
  variant: "top" | "dock";
  sections: OfficeSection[];
  agents: OfficeAgent[];
  tasks: OfficeTask[];
  roles: Record<string, OfficeRole>;
  selectedSections: string[];
  selectedRoles: string[];
  openSection: string;
  onToggleSection: (id: string, additive: boolean) => void;
  onOpenSection: (id: string) => void;
  onToggleRole?: (roleId: string, additive: boolean) => void;
}

export function SectionBar(props: SectionBarProps) {
  const { variant, sections, agents, tasks, roles, selectedSections, selectedRoles, openSection } = props;
  const picked = new Set(selectedSections);
  const pickedRoles = new Set(selectedRoles);

  const roleCounts = new Map<string, number>();
  agents.forEach((agent) => roleCounts.set(agent.role, (roleCounts.get(agent.role) ?? 0) + 1));

  return (
    <div className={`ofc-bar ofc-bar--${variant}`}>
      <div className="ofc-bar__rail" role="group" aria-label="Sections">
        {sections.length === 0 && <p className="ofc-bar__empty">No sections yet — give the office a task.</p>}
        {sections.map((section) => {
          const staff = agents.filter((a) => a.section_id === section.id);
          const working = staff.filter((a) => a.status === "working").length;
          const own = tasks.filter((t) => t.section_id === section.id);
          const done = own.filter((t) => t.status === "done").length;
          const progress = own.length ? Math.round((done / own.length) * 100) : 0;
          return (
            <button key={section.id} type="button"
                    className={`ofc-box${picked.has(section.id) ? " is-picked" : ""}`
                      + (openSection === section.id ? " is-open" : "")
                      + (section.status !== "active" ? " is-paused" : "")}
                    style={{ ["--room" as string]: section.color }}
                    aria-pressed={picked.has(section.id)}
                    title={`${section.purpose || section.name}\nClick to select · double-click to open${
                      section.status !== "active" ? `\n${section.status}` : ""}`}
                    onClick={(event) => props.onToggleSection(section.id, event.shiftKey || event.metaKey || event.ctrlKey)}
                    onDoubleClick={() => props.onOpenSection(section.id)}>
              <span className="ofc-box__name">{section.name}</span>
              <span className="ofc-box__meta">
                {staff.length} {staff.length === 1 ? "agent" : "agents"}
                {working > 0 && <em className="ofc-box__live"> · {working} working</em>}
              </span>
              {own.length > 0 && (
                <span className="ofc-box__bar" aria-hidden="true">
                  <span style={{ width: `${progress}%` }} />
                </span>
              )}
              {variant === "dock" && own.length > 0 && (
                <span className="ofc-box__tasks">{done}/{own.length} done</span>
              )}
            </button>
          );
        })}
      </div>

      {variant === "dock" && props.onToggleRole && (
        <div className="ofc-bar__kinds" role="group" aria-label="Kinds of agent">
          <span className="ofc-bar__label">Kinds</span>
          {[...roleCounts.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([roleId, count]) => {
              const role = roles[roleId];
              return (
                <button key={roleId} type="button"
                        className={`ofc-kind${pickedRoles.has(roleId) ? " is-picked" : ""}`}
                        style={{ ["--kind" as string]: role?.color ?? "#9397ab" }}
                        aria-pressed={pickedRoles.has(roleId)}
                        title={role?.goal || roleId}
                        onClick={(event) => props.onToggleRole?.(roleId, event.shiftKey || event.metaKey || event.ctrlKey)}>
                  <span className="ofc-kind__glyph">{role?.glyph ?? "●"}</span>
                  {role?.title ?? roleId}
                  <span className="ofc-kind__count">{count}</span>
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
}
