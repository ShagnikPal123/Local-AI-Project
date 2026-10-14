/** Colour and layout choices (owner, 2026-10-10: "in settings I would like the option for color changes, and switching
 * the left bar to a different side or on top or bottom"). Kept in this browser and applied before the first paint.
 * The accent overrides whatever the style mix set, and its lighter/darker steps are derived so every page follows. */

export type NavSide = "left" | "right" | "top" | "bottom";
/** "" = the look decides: the left icon rail in Studio Glass, the strip across the top in every other look. */
export type NavChoice = NavSide | "";

/** Where the navigation bar really goes. Every look now honours the owner's pick (S4: it used to work only in Studio Glass). */
export function effectiveNav(choice: NavChoice, studio: boolean): NavSide {
  return choice || (studio ? "left" : "top");
}

export const ACCENTS: { id: string; label: string; hex: string }[] = [
  { id: "", label: "Style default", hex: "" },
  { id: "orange", label: "Ember", hex: "#ff7a2e" },
  { id: "violet", label: "Violet", hex: "#a594ff" },
  { id: "cyan", label: "Cyan", hex: "#5fd4f4" },
  { id: "mint", label: "Mint", hex: "#6fe3b4" },
  { id: "pink", label: "Rose", hex: "#f39bd6" },
  { id: "amber", label: "Amber", hex: "#ffc46b" },
  { id: "coral", label: "Coral", hex: "#ff8a8a" },
  { id: "sky", label: "Sky", hex: "#8fb4ff" },
];

const KEY = "ichos.appearance";
interface Saved { accent: string; nav: NavChoice; sync: boolean }

export function readAppearance(): Saved {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    // `navSet` marks a pick made on purpose. Older saves wrote "left" for everyone who only changed the accent,
    // and that must not move the strip of a look that never had a rail.
    const chosen = raw.navSet === true && ["left", "right", "top", "bottom"].includes(raw.nav);
    return { accent: typeof raw.accent === "string" ? raw.accent : "", nav: chosen ? raw.nav : "", sync: raw.sync === true };
  } catch {
    return { accent: "", nav: "", sync: false };
  }
}

function mix(hex: string, target: number, share: number): string {
  const n = parseInt(hex.slice(1), 16);
  const parts = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => Math.round(c + (target - c) * share));
  return `#${parts.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

const ACCENT_VARS = ["--color-accent", "--color-accent-2", "--color-accent-300", "--color-accent-400", "--color-accent-500",
  "--color-accent-700", "--color-accent-900", "--color-link", "--pop-violet", "--studio-orange"];

/** Paint the accent (or hand it back to the look when empty). The shell's theme loader calls this too: an untouched
 * server theme clears inline colours on load, which used to wipe the owner's pick until the next change. */
export function applyAccent(accent: string): void {
  const root = document.documentElement;
  if (/^#[0-9a-f]{6}$/i.test(accent)) {
    const a = accent;
    const values = [a, mix(a, 255, 0.25), mix(a, 255, 0.55), mix(a, 255, 0.25), a, mix(a, 0, 0.35), mix(a, 0, 0.78), mix(a, 255, 0.3), a, a];
    ACCENT_VARS.forEach((name, i) => root.style.setProperty(name, values[i]));
  } else {
    ACCENT_VARS.forEach((name) => root.style.removeProperty(name));
  }
}

/** What the desktop looks like (engine: desktop_theme.py). Filled in by style/desktopSync.ts while syncing is on. */
export interface DesktopTheme { available: boolean; accent: string | null; dark: boolean | null; wallpaper_color: string | null }
let desktop: DesktopTheme | null = null;

const SURFACE_VARS: [string, string][] = [
  ["--color-bg", "#121319"], ["--color-nav", "#0e0f15"], ["--color-surface", "#1a1c25"],
  ["--color-surface-2", "#20232f"], ["--color-surface-3", "#2a2e3e"], ["--color-flyout", "#1d202b"],
];

/** The accent the page should wear now: the desktop's while syncing (and known), else the owner's own pick. */
export function effectiveAccent(saved: Saved = readAppearance()): string {
  return saved.sync && desktop?.accent ? desktop.accent : saved.accent;
}

/** Paint accent and surfaces from the owner's pick and, when syncing, from the desktop. The app stays dark, so the
 * wallpaper only tints the dark surfaces a little (12%): enough to feel like the desktop, never enough to hurt reading. */
export function paintTheme(): void {
  const saved = readAppearance();
  applyAccent(effectiveAccent(saved));
  const root = document.documentElement;
  const wall = saved.sync && desktop?.wallpaper_color && /^#[0-9a-f]{6}$/i.test(desktop.wallpaper_color) ? desktop.wallpaper_color : "";
  SURFACE_VARS.forEach(([name, base]) => (wall ? root.style.setProperty(name, mixHex(base, wall, 0.12)) : root.style.removeProperty(name)));
}

export function setDesktopTheme(next: DesktopTheme | null): void {
  desktop = next;
  paintTheme();
}

function mixHex(base: string, other: string, share: number): string {
  const a = parseInt(base.slice(1), 16), b = parseInt(other.slice(1), 16);
  const part = (shift: number) => Math.round(((a >> shift) & 255) * (1 - share) + ((b >> shift) & 255) * share);
  return `#${[16, 8, 0].map((sh) => part(sh).toString(16).padStart(2, "0")).join("")}`;
}

export function applyAppearance(next: Partial<Saved> = {}): Saved {
  const saved = { ...readAppearance(), ...next };
  try { localStorage.setItem(KEY, JSON.stringify({ ...saved, navSet: saved.nav !== "" })); } catch { /* not kept */ }
  const root = document.documentElement;
  // The shell turns this choice into <html data-nav> once it knows the look (style/useNavSide.ts).
  root.dataset.navChoice = saved.nav;
  paintTheme();
  window.dispatchEvent(new CustomEvent("ichos:appearance", { detail: saved }));
  return saved;
}

export function bootAppearance(): void {
  applyAppearance();
}
