/** Colour and layout choices (owner, 2026-10-10: "in settings I would like the option for color changes, and switching
 * the left bar to a different side or on top or bottom"). Kept in this browser and applied before the first paint.
 * The accent overrides whatever the style mix set, and its lighter/darker steps are derived so every page follows. */

export type NavSide = "left" | "right" | "top" | "bottom";

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
interface Saved { accent: string; nav: NavSide }

export function readAppearance(): Saved {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { accent: typeof raw.accent === "string" ? raw.accent : "", nav: ["left", "right", "top", "bottom"].includes(raw.nav) ? raw.nav : "left" };
  } catch {
    return { accent: "", nav: "left" };
  }
}

function mix(hex: string, target: number, share: number): string {
  const n = parseInt(hex.slice(1), 16);
  const parts = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => Math.round(c + (target - c) * share));
  return `#${parts.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

const ACCENT_VARS = ["--color-accent", "--color-accent-2", "--color-accent-300", "--color-accent-400", "--color-accent-500",
  "--color-accent-700", "--color-accent-900", "--color-link", "--pop-violet", "--studio-orange"];

export function applyAppearance(next: Partial<Saved> = {}): Saved {
  const saved = { ...readAppearance(), ...next };
  try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* not kept */ }
  const root = document.documentElement;
  root.dataset.nav = saved.nav;
  if (/^#[0-9a-f]{6}$/i.test(saved.accent)) {
    const a = saved.accent;
    const values = [a, mix(a, 255, 0.25), mix(a, 255, 0.55), mix(a, 255, 0.25), a, mix(a, 0, 0.35), mix(a, 0, 0.78), mix(a, 255, 0.3), a, a];
    ACCENT_VARS.forEach((name, i) => root.style.setProperty(name, values[i]));
  } else {
    ACCENT_VARS.forEach((name) => root.style.removeProperty(name));
  }
  window.dispatchEvent(new CustomEvent("ichos:appearance", { detail: saved }));
  return saved;
}

export function bootAppearance(): void {
  applyAppearance();
}
