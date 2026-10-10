/** Settings, as its own window over the app (redesign 2026-10-10).
 *
 * The owner: "Dashboard, power, settings, sessions & memory … are combined and have tabs. This settings will rather
 * be a button on top … revamp settings in how it looks and feels." So Settings left the tab strip. It opens from the
 * gear in the top bar, the way Windows 11 Settings looks: a navigation list on the left (grouped, with icons), the
 * page on the right with a big title, cards with one job each. Design Research lives here too — it is optional now.
 *
 * Esc or the close button returns to whatever was open. The last page is remembered.
 */

import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { SettingsGroup } from "../../panels/SettingsPanel";
import { HubContext } from "../Panel";
import "./settings.css";

const SettingsPanel = lazy(() => import("../../panels/SettingsPanel").then((m) => ({ default: m.SettingsPanel })));
const DashboardPanel = lazy(() => import("../../panels/DashboardPanel").then((m) => ({ default: m.DashboardPanel })));
const PowerPanel = lazy(() => import("../../panels/PowerPanel").then((m) => ({ default: m.PowerPanel })));
const WorkPanel = lazy(() => import("../../panels/WorkPanel").then((m) => ({ default: m.WorkPanel })));
const DesignResearchPanel = lazy(() => import("../../panels/design/DesignResearchPanel").then((m) => ({ default: m.DesignResearchPanel })));

export type SettingsPage = SettingsGroup | "status" | "power" | "memory" | "design";

interface Page { id: SettingsPage; label: string; glyph: string; purpose: string }

const GROUPS: { title: string; pages: Page[] }[] = [
  {
    title: "Ichos",
    pages: [
      { id: "general", label: "General", glyph: "⚙", purpose: "The engine, how Ichos opens, safety and response speed." },
      { id: "intelligence", label: "Intelligence", glyph: "✦", purpose: "How Ichos thinks: models per job, personality, your mods." },
      { id: "voice", label: "Voice", glyph: "◉", purpose: "Voices you can hear before choosing, and the sounds Ichos answers to." },
      { id: "appearance", label: "Appearance", glyph: "◐", purpose: "Background and content settings." },
      { id: "storage", label: "Storage", glyph: "▤", purpose: "What Ichos keeps on this PC, and how much room it takes." },
    ],
  },
  {
    title: "This PC",
    pages: [
      { id: "status", label: "Status", glyph: "▦", purpose: "Live device, routing and safety status." },
      { id: "power", label: "Power", glyph: "ϟ", purpose: "Shut down, restart, sleep — and when Ichos may do it." },
      { id: "memory", label: "Sessions & memory", glyph: "◎", purpose: "What Ichos remembers, and where it lives." },
    ],
  },
  {
    title: "Optional",
    pages: [
      { id: "design", label: "Design research", glyph: "◇", purpose: "Study how sites look; Ichos designs with what it kept." },
    ],
  },
];

const PAGES = GROUPS.flatMap((g) => g.pages);
const KEY = "ichos.settings.page";

/** Open Settings at a page from anywhere (old tab links, the host pill, Nyx's ui_open_tab). */
export function openSettings(page?: SettingsPage): void {
  window.dispatchEvent(new CustomEvent("ichos:open-settings", { detail: { page } }));
}

export function SettingsWindow({ initial, onClose }: { initial?: SettingsPage; onClose: () => void }) {
  const [page, setPage] = useState<SettingsPage>(() => {
    if (initial) return initial;
    try {
      const saved = localStorage.getItem(KEY) as SettingsPage | null;
      if (saved && PAGES.some((p) => p.id === saved)) return saved;
    } catch { /* not kept */ }
    return "general";
  });
  useEffect(() => { if (initial) setPage(initial); }, [initial]);
  useEffect(() => { try { localStorage.setItem(KEY, page); } catch { /* not kept */ } }, [page]);

  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    opener.current = document.activeElement;
    panel.current?.querySelector<HTMLElement>("[aria-current='page']")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [onClose]);

  const current = PAGES.find((p) => p.id === page) ?? PAGES[0];

  return (
    <div className="settings-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="settings-window" role="dialog" aria-modal="true" aria-label="Settings" ref={panel}>
        <nav className="settings-nav" aria-label="Settings pages">
          <div className="settings-nav__title">Settings</div>
          {GROUPS.map((group) => (
            <div key={group.title} className="settings-nav__group">
              <div className="settings-nav__group-title">{group.title}</div>
              {group.pages.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="settings-nav__item"
                  aria-current={p.id === page ? "page" : undefined}
                  onClick={() => setPage(p.id)}
                >
                  <span className="settings-nav__glyph" aria-hidden="true">{p.glyph}</span>
                  {p.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <section className="settings-page" aria-labelledby="settings-page-title">
          <header className="settings-page__head">
            <div>
              <h1 id="settings-page-title" className="settings-page__title">{current.label}</h1>
              <p className="settings-page__purpose">{current.purpose}</p>
            </div>
            <button type="button" className="btn btn-ghost settings-page__close" onClick={onClose} aria-label="Close settings" title="Close (Esc)">✕</button>
          </header>
          <div className="settings-page__body">
            <HubContext.Provider value={true}>
              <Suspense fallback={<div className="tab-loading" role="status"><span className="tab-loading__dot" />Opening {current.label}…</div>}>
                {(["general", "intelligence", "voice", "appearance", "storage"] as const).includes(page as SettingsGroup)
                  && <SettingsPanel group={page as SettingsGroup} />}
                {page === "status" && <DashboardPanel />}
                {page === "power" && <PowerPanel />}
                {page === "memory" && <WorkPanel />}
                {page === "design" && <DesignResearchPanel />}
              </Suspense>
            </HubContext.Provider>
          </div>
        </section>
      </div>
    </div>
  );
}
