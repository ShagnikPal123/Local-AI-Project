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
  | "jarvis"
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
  // Brain + chat + voice together (Request F). "strands" and "chat" open this tab.
  { id: "nyx", label: "Nyx", icon: "ph-brain", pinned: true, core: true },
  { id: "build", label: "Build", icon: "ph-cube", pinned: true, core: true },
  { id: "games", label: "Game Studio", icon: "ph-game-controller", pinned: true, core: true },
  { id: "research", label: "Research", icon: "ph-magnifying-glass", pinned: true, core: true },
  { id: "learn", label: "Learn", icon: "ph-graduation-cap", pinned: true, core: true },
  { id: "notes", label: "Notes", icon: "ph-note-pencil", pinned: true, core: true },
  { id: "code", label: "Code", icon: "ph-code", pinned: true, core: true },
  { id: "subagents", label: "Sub-agents", icon: "ph-users-three", pinned: true, core: true },
  { id: "collab", label: "Collab", icon: "ph-git-pull-request", pinned: false, core: true },
  { id: "trading", label: "Trading", icon: "ph-chart-line-up", pinned: true, core: true },
  { id: "improve", label: "Improve", icon: "ph-arrows-clockwise", pinned: true, core: true },
  // Request R: Nyx studies documents and grows from them, with the owner watching and approving what it adds.
  { id: "absorb", label: "Data Absorption", icon: "ph-waveform", pinned: true, core: true },
  // Request R10: Nyx looks at a shared screen or window and helps one approved step at a time.
  { id: "screen", label: "Screen Share", icon: "ph-screencast", pinned: true, core: true },
  // Request R16: prompt + files/pictures/links → Nyx plans changes to itself; each applies only on the owner's press.
  { id: "apply", label: "Apply", icon: "ph-magic-wand", pinned: true, core: true },
  // Request R15: Nyx with opinions of its own, one guarded chat box; asks the owner's permission on first open.
  { id: "freewill", label: "Free Will", icon: "ph-sparkle", pinned: true, core: true },
  // Request S: Identity 0 — the main brain that picks, compares and learns; ID0 + All companion lives here too.
  { id: "kahuna", label: "Big Kahuna", icon: "ph-crown-simple", pinned: true, core: true },
  // Project Null N8: a whole office of agents — hierarchy, sections, and the owner watching them work.
  { id: "office", label: "Office Space", icon: "ph-buildings", pinned: true, core: true },
  // UPDATE_IDEAS U34–U40: the AI Environment — an office upscaled into a planet that grows as its AIs deliver.
  { id: "world", label: "World", icon: "ph-globe-hemisphere-west", pinned: true, core: true },
  // UPDATE_IDEAS U2: draw, and Nyx draws with you — scan to improve, a bar for what Nyx should draw.
  { id: "sketch", label: "Create", icon: "ph-paint-brush", pinned: true, core: true },
  // From the Jarvis projects (2026-10-09): talk to Nyx, what needs you, Claude Code sessions, the morning digest.
  { id: "jarvis", label: "Jarvis", icon: "ph-circles-three", pinned: true, core: true },
  // The Design Masterplan's research log as a feature: study how sites look; Nyx designs with what it kept.
  { id: "design_research", label: "Design Research", icon: "ph-palette", pinned: true, core: true },
  // Update 1, U49: a sandboxed desktop of Nyx's own (Cua), and where it may work — never borrowing yours unasked.
  { id: "computer", label: "Nyx's Computer", icon: "ph-desktop-tower", pinned: true, core: true },
  { id: "dashboard", label: "Dashboard", icon: "ph-radar", pinned: false, core: true },
  { id: "work", label: "Sessions & Memory", icon: "ph-clock-counter-clockwise", pinned: false, core: true },
  { id: "models", label: "Models", icon: "ph-cpu", pinned: false, core: true },
  { id: "keys", label: "Keys & Models", icon: "ph-key", pinned: true, core: true },
  { id: "agents", label: "Agents", icon: "ph-tree-structure", pinned: false, core: true },
  { id: "connectors", label: "Connectors", icon: "ph-plugs", pinned: false, core: true },
  { id: "store", label: "Add capability", icon: "ph-plus-circle", pinned: false, core: true },
  { id: "power", label: "Power", icon: "ph-lightning", pinned: false, core: true },
  { id: "strands", label: "Strands (classic)", icon: "ph-graph", pinned: false, core: true },
  { id: "admin", label: "Admin", icon: "ph-shield-check", pinned: false, core: true, adminOnly: true },
  { id: "settings", label: "Settings", icon: "ph-gear-six", pinned: false, core: true },
];

export type ShellLayout = "rail" | "strip";
