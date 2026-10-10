/** A merged tab: one heading, a row of sections, and the chosen section below (redesign 2026-10-10).
 *
 * The owner folded related tabs together — Research + Data Absorption + Apply, Agents + Sub-agents, the computer and
 * screen sharing, Connectors + Keys + Models + Add capability. Each old tab lives on as a section, so nothing it did is
 * lost, and its own page header steps aside (HubContext) because the hub already says where you are.
 *
 * The chosen section is remembered per hub. `openSection(hub, section)` jumps straight to one — old links to the
 * tabs that were merged (and Nyx's ui_open_tab) land on the right section through it.
 */

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { HubContext } from "./Panel";

export interface HubSection {
  id: string;
  label: string;
  /** One line under the heading while this section is open. */
  purpose: string;
  render: () => ReactNode;
}

const key = (hub: string) => `ichos.hub.${hub}`;

/** Ask a hub to show one of its sections (works whether or not the hub is open yet). */
export function openSection(hub: string, section: string): void {
  try { localStorage.setItem(key(hub), section); } catch { /* not kept in private windows */ }
  window.dispatchEvent(new CustomEvent("ichos:open-section", { detail: { hub, section } }));
}

export function HubPanel({ id, title, sections }: { id: string; title: string; sections: HubSection[] }) {
  const [current, setCurrent] = useState(() => {
    try {
      const saved = localStorage.getItem(key(id));
      if (saved && sections.some((s) => s.id === saved)) return saved;
    } catch { /* not kept */ }
    return sections[0].id;
  });
  useEffect(() => { try { localStorage.setItem(key(id), current); } catch { /* not kept */ } }, [id, current]);
  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ hub: string; section: string }>).detail;
      if (detail?.hub === id && sections.some((s) => s.id === detail.section)) setCurrent(detail.section);
    };
    window.addEventListener("ichos:open-section", onOpen);
    return () => window.removeEventListener("ichos:open-section", onOpen);
  }, [id, sections]);

  const section = sections.find((s) => s.id === current) ?? sections[0];

  return (
    <div className="hub">
      <header className="hub__head">
        <div className="hub__titles">
          <h1 className="hub__title">{title}</h1>
          <p className="hub__purpose">{section.purpose}</p>
        </div>
        <nav className="hub__pivot" role="tablist" aria-label={`${title} sections`}>
          {sections.map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={s.id === section.id}
              className="hub__pivot-item"
              onClick={() => setCurrent(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="hub__body" role="tabpanel" aria-label={section.label}>
        <HubContext.Provider value={true}>
          <Suspense fallback={<div className="tab-loading" role="status"><span className="tab-loading__dot" />Opening {section.label}…</div>}>
            {section.render()}
          </Suspense>
        </HubContext.Provider>
      </div>
    </div>
  );
}
