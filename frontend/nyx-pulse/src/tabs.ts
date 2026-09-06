/** Tab model for the workspace shell, matching the design handoff. */

export type TabId =
  | "strands"
  | "chat"
  | "dashboard"
  | "work"
  | "models"
  | "agents"
  | "connectors"
  | "store"
  | "power"
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
  { id: "strands", label: "Strands", icon: "ph-graph", pinned: true, core: true },
  { id: "chat", label: "Chat", icon: "ph-chat-teardrop-dots", pinned: true, core: true },
  { id: "dashboard", label: "Dashboard", icon: "ph-radar", pinned: true, core: true },
  { id: "work", label: "Sessions & Memory", icon: "ph-clock-counter-clockwise", pinned: false, core: true },
  { id: "models", label: "Models", icon: "ph-cpu", pinned: false, core: true },
  { id: "agents", label: "Agents", icon: "ph-tree-structure", pinned: false, core: true },
  { id: "connectors", label: "Connectors", icon: "ph-plugs", pinned: false, core: true },
  { id: "store", label: "Add capability", icon: "ph-plus-circle", pinned: true, core: true },
  { id: "power", label: "Power", icon: "ph-lightning", pinned: false, core: true },
  { id: "admin", label: "Admin", icon: "ph-shield-check", pinned: false, core: true, adminOnly: true },
  { id: "settings", label: "Settings", icon: "ph-gear-six", pinned: false, core: true },
];

export type ShellLayout = "rail" | "strip";
