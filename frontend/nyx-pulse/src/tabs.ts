/** Tab model for the workspace shell, matching the design handoff. */

export type TabId =
  | "nyx"
  | "build"
  | "games"
  | "research"
  | "learn"
  | "notes"
  | "code"
  | "subagents"
  | "collab"
  | "trading"
  | "strands"
  | "chat"
  | "dashboard"
  | "work"
  | "models"
  | "keys"
  | "agents"
  | "connectors"
  | "store"
  | "power"
  | "improve"
  | "absorb"
  | "screen"
  | "apply"
  | "freewill"
  | "kahuna"
  | "office"
  | "world"
  | "sketch"
  | "equalize"
  | "predict"
  | "avatars"
  | "projects"
  | "artifacts"
  | "scheduled"
  | "design"
  | "design_research"
  | "computer"
  | "admin"
  | "settings";

export interface TabDef {
  id: TabId;
  label: string;
  /** Phosphor icon name, as used in the design. */
  icon: string;
  /** Pinned tabs sort first and cannot be closed. */
  pinned: boolean;
  /** Core tabs ship with the app and cannot be removed. */
  core: boolean;
  /** Hidden unless the signed-in account can actually use it. */
  adminOnly?: boolean;
}

/** Roles allowed to see admin-only tabs. Mirrors the server-side permission. */
const ADMIN_ROLES = new Set(["owner", "admin"]);

/**
 * Tabs this account should see.
 *
 * This is presentation only — the server enforces the real boundary on every
 * request. Hiding a tab is a courtesy, not a security control.
 */
export function visibleTabs(role: string | undefined): TabDef[] {
  return CORE_TABS.filter((t) => !t.adminOnly || ADMIN_ROLES.has(role ?? ""));
}

export const CORE_TABS: TabDef[] = [
  // Redesign 2026-10-10 (owner): chat is home, and Game Studio, drawing and the Second Brain open as windows inside it.
  { id: "nyx", label: "Chat", icon: "ph-chat-circle", pinned: true, core: true },
  // Research + Data Absorption + Apply, one tab with three sections.
  { id: "research", label: "Research Lab", icon: "ph-magnifying-glass", pinned: true, core: true },
  { id: "learn", label: "Learn", icon: "ph-graduation-cap", pinned: true, core: true },
  { id: "code", label: "Code", icon: "ph-code", pinned: true, core: true },
  // Agents + Sub-agents.
  { id: "agents", label: "Agents", icon: "ph-tree-structure", pinned: true, core: true },
  { id: "collab", label: "Collab · WIP", icon: "ph-git-pull-request", pinned: false, core: true },
  { id: "trading", label: "Trading", icon: "ph-chart-line-up", pinned: true, core: true },
  { id: "improve", label: "Improve", icon: "ph-arrows-clockwise", pinned: true, core: true },
  { id: "freewill", label: "Free Will", icon: "ph-sparkle", pinned: true, core: true },
  { id: "kahuna", label: "Big Kahuna", icon: "ph-crown-simple", pinned: true, core: true },
  // Office Space + World (+ the court they share).
  { id: "office", label: "Office & World", icon: "ph-buildings", pinned: true, core: true },
  { id: "equalize", label: "Equalize", icon: "ph-circles-three", pinned: true, core: true },
  // A swarm of simulated people forecasts anything (predict.py; the MiroFish idea, owner 2026-10-10).
  { id: "predict", label: "Predict", icon: "ph-crystal-ball", pinned: true, core: true },
  // Always-on helpers the owner shapes (avatars.py): main function, schedule, functions, goals, watches, taught tasks.
  { id: "avatars", label: "Avatars", icon: "ph-users-three", pinned: true, core: true },
  // Sidebar of the owner's reference (2026-10-11): Projects, Artifacts, Scheduled, Design — space / maths names, plain subtitles.
  { id: "projects", label: "Constellations", icon: "ph-planet", pinned: true, core: true },
  { id: "artifacts", label: "Quasars", icon: "ph-sparkle", pinned: true, core: true },
  { id: "scheduled", label: "Orbits", icon: "ph-clock-clockwise", pinned: true, core: true },
  { id: "design", label: "Fractal", icon: "ph-pen-nib", pinned: true, core: true },
  // Ichos's own computer + Screen Share.
  { id: "computer", label: "Computer", icon: "ph-desktop-tower", pinned: true, core: true },
  // Connectors + Keys & Models + Models + Add capability.
  { id: "connectors", label: "Connections", icon: "ph-plugs", pinned: true, core: true },
  { id: "admin", label: "Admin · WIP", icon: "ph-shield-check", pinned: false, core: true, adminOnly: true },
];

/** Where a tab that was merged or removed now lives, so old links, Nyx's ui_open_tab and habits still land.
 *  `hub` + `section` open a section of a merged tab; `settings` opens a Settings page; `window` opens in chat. */
export type Redirect =
  | { kind: "hub"; tab: TabId; section: string }
  | { kind: "settings"; page: "general" | "status" | "power" | "memory" | "design" }
  | { kind: "window"; window: "game" | "brain" | "screen" | "build" | "notes" };

export const REDIRECTS: Record<string, Redirect> = {
  chat: { kind: "hub", tab: "nyx", section: "" },
  strands: { kind: "hub", tab: "nyx", section: "" },
  games: { kind: "window", window: "game" },
  // Owner, 2026-10-10: Build and Notes live in the chat now (abilities in the composer); old links open them full size.
  build: { kind: "window", window: "build" },
  notes: { kind: "window", window: "notes" },
  world: { kind: "hub", tab: "office", section: "world" },
  court: { kind: "hub", tab: "office", section: "court" },
  sketch: { kind: "hub", tab: "nyx", section: "" },
  absorb: { kind: "hub", tab: "research", section: "absorb" },
  apply: { kind: "hub", tab: "research", section: "apply" },
  subagents: { kind: "hub", tab: "agents", section: "subagents" },
  screen: { kind: "hub", tab: "computer", section: "screen" },
  models: { kind: "hub", tab: "connectors", section: "models" },
  keys: { kind: "hub", tab: "connectors", section: "keys" },
  store: { kind: "hub", tab: "connectors", section: "store" },
  settings: { kind: "settings", page: "general" },
  dashboard: { kind: "settings", page: "status" },
  power: { kind: "settings", page: "power" },
  work: { kind: "settings", page: "memory" },
  design_research: { kind: "settings", page: "design" },
};

/** Old names people (and Nyx) still say, so voice and ui_open_tab can find the new home. */
export const LEGACY_LABELS: { id: string; label: string }[] = [
  { id: "games", label: "Game Studio" }, { id: "sketch", label: "Create" }, { id: "absorb", label: "Data Absorption" },
  { id: "apply", label: "Apply" }, { id: "subagents", label: "Sub-agents" }, { id: "screen", label: "Screen Share" },
  { id: "models", label: "Models" }, { id: "keys", label: "Keys & Models" }, { id: "store", label: "Add capability" },
  { id: "settings", label: "Settings" }, { id: "dashboard", label: "Dashboard" }, { id: "power", label: "Power" },
  { id: "work", label: "Sessions & Memory" }, { id: "design_research", label: "Design Research" },
  { id: "computer", label: "Nyx's Computer" }, { id: "world", label: "World" }, { id: "office", label: "Office Space" },
  { id: "projects", label: "Projects" }, { id: "artifacts", label: "Artifacts" }, { id: "scheduled", label: "Scheduled" },
  { id: "design", label: "Design" }, { id: "court", label: "Court" }, { id: "nyx", label: "Nyx" }, { id: "nyx", label: "Second Brain" },
];

export type ShellLayout = "rail" | "strip";
