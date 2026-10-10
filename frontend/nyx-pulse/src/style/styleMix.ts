/** The style mixer (owner, 2026-10-10: "use these designs and try to mix and combine them").
 *
 * Each of the owner's twenty styles is a layer of CSS (style/styles.css) switched on by a word in
 * `<html data-style="…">`. They stack: Signature — the default — is gradient mesh + glass + neon glow + holographic +
 * particles + kinetic type + split-flap + liquid morph. Presets are curated mixes; every style can also be toggled on
 * its own in Settings › Appearance. Kept in this browser (it is a look, not data) and applied before the first paint.
 */

import { useEffect, useState } from "react";

export const STYLES = [
  { id: "studio", label: "Studio Glass", hint: "Floating glass panels over a warm backdrop, orange accent, icon rail, dashboard home" },
  { id: "particles", label: "Particles", hint: "A slow field of points behind everything" },
  { id: "liquid", label: "Liquid morph", hint: "Soft blobs that change shape behind headers" },
  { id: "holo", label: "Holographic", hint: "A shifting sheen on primary buttons and the active tab" },
  { id: "neon", label: "Neon glow", hint: "Glow on what is active, focused or working" },
  { id: "wireframe", label: "Wireframe 3D", hint: "Cards drawn as outlines over a perspective grid" },
  { id: "glass", label: "Glassmorphism", hint: "Frosted, see-through panels" },
  { id: "kinetic", label: "Kinetic type", hint: "Titles that move in when a page opens" },
  { id: "isometric", label: "Isometric", hint: "Isometric blocks in page headers" },
  { id: "clay", label: "Clay 3D", hint: "Soft, puffy, pressable surfaces" },
  { id: "ascii", label: "ASCII art", hint: "Monospace titles with box-drawing frames" },
  { id: "brutal", label: "Neo-brutalism", hint: "Thick outlines and hard offset shadows" },
  { id: "mesh", label: "Gradient mesh", hint: "A soft colour mesh behind the app" },
  { id: "comic", label: "Comic book", hint: "Bold ink outlines and speech-bubble corners" },
  { id: "splitflap", label: "Split-flap", hint: "Numbers flip like a departures board" },
  { id: "vhs", label: "Retro VHS", hint: "Scanlines and a little colour bleed" },
  { id: "halftone", label: "Halftone", hint: "Print dots in the shading" },
  { id: "bauhaus", label: "Bauhaus", hint: "Primary shapes and strict geometry" },
  { id: "pixel", label: "Pixel art", hint: "Square corners and stepped, pixel shadows" },
  { id: "blueprint", label: "Blueprint", hint: "Engineering grid on canvases and windows" },
  { id: "deco", label: "Art deco", hint: "Gold hairlines and fan ornaments" },
] as const;

export type StyleId = (typeof STYLES)[number]["id"];

export const PRESETS: { id: string; label: string; styles: StyleId[]; hint: string }[] = [
  // Owner, 2026-10-10: "make the AI look similar" to a glassy dashboard reference, with our own touches — the default.
  { id: "studio-glass", label: "Studio Glass", hint: "Floating glass panels, orange accent, icon rail, dashboard home", styles: ["studio", "glass", "neon", "kinetic", "splitflap"] },
  { id: "signature", label: "Signature", hint: "Mesh, glass, neon, holographic, particles, moving type", styles: ["mesh", "glass", "neon", "holo", "particles", "kinetic", "splitflap", "liquid"] },
  { id: "holo-glass", label: "Holo Glass", hint: "See-through and shimmering", styles: ["holo", "glass", "mesh", "particles", "neon"] },
  { id: "blueprint-deco", label: "Blueprint Deco", hint: "Drafting grid with gold deco lines", styles: ["blueprint", "deco", "wireframe", "kinetic", "splitflap"] },
  { id: "arcade", label: "Arcade", hint: "Pixels, scanlines and neon", styles: ["pixel", "vhs", "neon", "splitflap", "ascii"] },
  { id: "comic-pop", label: "Comic Pop", hint: "Ink, dots and bold blocks", styles: ["comic", "halftone", "brutal", "bauhaus"] },
  { id: "clay-studio", label: "Clay Studio", hint: "Soft 3D clay and isometric blocks", styles: ["clay", "isometric", "liquid", "mesh"] },
  { id: "quiet", label: "Quiet", hint: "No effects — just the colours", styles: [] },
];

const KEY = "ichos.style.mix";
// Studio Glass arrived after mixes were already saved; it is added to a saved mix once, then left to the owner.
const STUDIO_SEEN = "ichos.style.studio-seen";

export function currentMix(): StyleId[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw !== null) {
      const saved: StyleId[] = JSON.parse(raw).filter((s: string) => STYLES.some((x) => x.id === s));
      if (localStorage.getItem(STUDIO_SEEN) === null) {
        localStorage.setItem(STUDIO_SEEN, "1");
        if (!saved.includes("studio")) saved.unshift("studio");
        localStorage.setItem(KEY, JSON.stringify(saved));
      }
      return saved;
    }
    localStorage.setItem(STUDIO_SEEN, "1");
  } catch { /* fall through */ }
  return PRESETS[0].styles;
}

export function applyMix(mix: StyleId[]): void {
  document.documentElement.dataset.style = mix.join(" ");
  try { localStorage.setItem(KEY, JSON.stringify(mix)); } catch { /* not kept */ }
  window.dispatchEvent(new CustomEvent("ichos:style-mix", { detail: mix }));
}

export function onMix(listener: (mix: StyleId[]) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<StyleId[]>).detail);
  window.addEventListener("ichos:style-mix", handler);
  return () => window.removeEventListener("ichos:style-mix", handler);
}

/** True while the given style is in the mix; follows Settings › Appearance live. */
export function useStyle(id: StyleId): boolean {
  const [on, setOn] = useState(() => currentMix().includes(id));
  useEffect(() => onMix((mix) => setOn(mix.includes(id))), [id]);
  return on;
}

/** Called once before React renders, so the chosen look is there on the first frame. */
export function bootMix(): void {
  document.documentElement.dataset.style = currentMix().join(" ");
}
