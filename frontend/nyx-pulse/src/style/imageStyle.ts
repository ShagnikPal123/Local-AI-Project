/** Style from an image (owner, 2026-10-15: "the user can input an image and the ai sees and tries to rearrange and
 * rewrite for that").
 *
 * Two readers, one result:
 *   1. Here, in the page: the picture's own pixels give the page, sidebar, panel, text and accent colours, and whether a
 *      darker or lighter column on the left (or a strip on top) suggests where the navigation sits. Instant and offline.
 *   2. The engine (/api/style/from-image): a model that can see adds what pixels can't: which colour does which job,
 *      the corner rounding, the density and the nav side. When no such model is set up, the page's own reading stands.
 * The result is a "look": only six-digit colours, a radius, a density and a side. It is previewed at once and kept or
 * undone by the owner (Settings › Appearance). Kept, it is the "From your image" palette over the Desk look.
 */

export interface ImageLook {
  background?: string; sidebar?: string; panel?: string; text?: string; muted?: string; accent?: string;
  radius?: number; density?: "compact" | "comfortable" | "spacious"; nav?: "left" | "right" | "top" | "bottom";
  dark?: boolean; name?: string; notes?: string;
}

const KEY = "ichos.style.image";
const HEX = /^#[0-9a-f]{6}$/i;

type RGB = [number, number, number];
const hex = ([r, g, b]: RGB) => `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;
const rgb = (h: string): RGB => { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
export const luminance = ([r, g, b]: RGB) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
const saturation = ([r, g, b]: RGB) => { const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return mx === 0 ? 0 : (mx - mn) / mx; };
const distance = (a: RGB, b: RGB) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
export const mixHex = (a: string, b: string, share: number) => {
  const x = rgb(a), y = rgb(b);
  return hex([0, 1, 2].map((i) => x[i] + (y[i] - x[i]) * share) as RGB);
};

/** The look a picture's pixels suggest. `pixels` is RGBA, `w` x `h` (the caller shrinks the image first). */
export function readPixels(pixels: Uint8ClampedArray, w: number, h: number): ImageLook {
  // Count colours in 4-bit-per-channel buckets, keeping each bucket's true average.
  const buckets = new Map<number, { n: number; sum: RGB }>();
  const column = (x0: number, x1: number, y0: number, y1: number): RGB => {
    const sum: RGB = [0, 0, 0]; let n = 0;
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const i = (y * w + x) * 4; sum[0] += pixels[i]; sum[1] += pixels[i + 1]; sum[2] += pixels[i + 2]; n++;
    }
    return n ? [sum[0] / n, sum[1] / n, sum[2] / n] : [0, 0, 0];
  };
  for (let i = 0; i < w * h * 4; i += 4) {
    if (pixels[i + 3] < 128) continue;
    const key = ((pixels[i] >> 4) << 8) | ((pixels[i + 1] >> 4) << 4) | (pixels[i + 2] >> 4);
    const b = buckets.get(key) ?? { n: 0, sum: [0, 0, 0] as RGB };
    b.n++; b.sum[0] += pixels[i]; b.sum[1] += pixels[i + 1]; b.sum[2] += pixels[i + 2];
    buckets.set(key, b);
  }
  const colours = [...buckets.values()].map((b) => ({ n: b.n, c: [b.sum[0] / b.n, b.sum[1] / b.n, b.sum[2] / b.n] as RGB }))
    .sort((a, b) => b.n - a.n);
  if (!colours.length) return {};
  const total = colours.reduce((s, x) => s + x.n, 0);
  const bg = colours[0].c;
  const dark = luminance(bg) < 0.45;
  // Panels: the commonest colour that is clearly not the page but close in brightness (a card, not text).
  const panel = colours.find((x) => x.n / total > 0.02 && distance(x.c, bg) > 6 && Math.abs(luminance(x.c) - luminance(bg)) < 0.18)?.c
    ?? (dark ? rgb(mixHex(hex(bg), "#ffffff", 0.05)) : rgb(mixHex(hex(bg), "#000000", 0.04)));
  // Text: the commonest colour with strong contrast to the page.
  const text = colours.find((x) => Math.abs(luminance(x.c) - luminance(bg)) > 0.5)?.c ?? (dark ? [232, 230, 225] as RGB : [26, 26, 26] as RGB);
  // Accent: vivid and present, weighted by how vivid.
  const accent = colours.filter((x) => saturation(x.c) > 0.35 && luminance(x.c) > 0.2 && luminance(x.c) < 0.9)
    .sort((a, b) => b.n * saturation(b.c) ** 2 - a.n * saturation(a.c) ** 2)[0]?.c;
  // Where the navigation sits: a left column or top strip that differs from the page.
  const left = column(0, Math.max(1, Math.round(w * 0.16)), 0, h);
  const rest = column(Math.round(w * 0.3), w, Math.round(h * 0.2), h);
  const top = column(0, w, 0, Math.max(1, Math.round(h * 0.08)));
  let nav: ImageLook["nav"];
  let sidebar: RGB = dark ? rgb(mixHex(hex(bg), "#000000", 0.25)) : rgb(mixHex(hex(bg), "#000000", 0.04));
  if (distance(left, rest) > 10) { nav = "left"; sidebar = left; }
  else if (distance(top, rest) > 10) { nav = "top"; sidebar = top; }
  const look: ImageLook = {
    background: hex(bg), panel: hex(panel), sidebar: hex(sidebar), text: hex(text),
    muted: mixHex(hex(text), hex(bg), 0.42), dark,
  };
  if (accent) look.accent = hex(accent);
  if (nav) look.nav = nav;
  return look;
}

/** Read a picture file in the page: shrink it to 96 px wide and look at its pixels. */
export async function readImageFile(file: File): Promise<{ look: ImageLook; dataUrl: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("That image could not be read."));
    reader.readAsDataURL(file);
  });
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("That file is not an image this app can open."));
    el.src = dataUrl;
  });
  const w = 96, h = Math.max(1, Math.round((img.naturalHeight / Math.max(1, img.naturalWidth)) * 96));
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This window cannot read images.");
  ctx.drawImage(img, 0, 0, w, h);
  return { look: readPixels(ctx.getImageData(0, 0, w, h).data, w, h), dataUrl };
}

/** The model's reading wins where it gave a value; the page's own reading fills the rest. */
export function mergeLooks(local: ImageLook, seen: ImageLook | null): ImageLook {
  if (!seen) return local;
  const out: ImageLook = { ...local };
  (Object.keys(seen) as (keyof ImageLook)[]).forEach((k) => {
    const v = seen[k];
    if (v === undefined || v === null || v === "") return;
    if (["background", "sidebar", "panel", "text", "muted", "accent"].includes(k) && !HEX.test(String(v))) return;
    (out as Record<string, unknown>)[k] = v;
  });
  return out;
}

export function readSavedLook(): ImageLook | null {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return v && typeof v === "object" ? v as ImageLook : null; }
  catch { return null; }
}
export function saveLook(look: ImageLook | null): void {
  try { if (look) localStorage.setItem(KEY, JSON.stringify(look)); else localStorage.removeItem(KEY); } catch { /* not kept */ }
}

const LOOK_VARS = ["--desk-sidebar", "--desk-main", "--desk-panel", "--desk-raised", "--desk-hover", "--desk-head", "--desk-user",
  "--desk-text", "--desk-muted", "--desk-faint", "--desk-line", "--desk-line-strong", "--color-surface-3", "--color-flyout",
  "--radius", "--radius-lg", "--radius-xl", "--look-gap"];
const LOOK_ACCENT = ["--color-accent", "--color-accent-2", "--color-accent-300", "--color-accent-400", "--color-accent-500",
  "--color-accent-700", "--studio-orange"];

/** Put a look on the page (inline on <html>), or take it off with null. `keepAccent` leaves an accent the owner picked. */
export function paintLook(look: ImageLook | null, keepAccent = false): void {
  const root = document.documentElement;
  if (!look) {
    LOOK_VARS.forEach((v) => root.style.removeProperty(v));
    if (!keepAccent) LOOK_ACCENT.forEach((v) => root.style.removeProperty(v));
    delete root.dataset.look;
    return;
  }
  const bg = look.background ?? "#151515";
  const dark = look.dark ?? luminance(rgb(bg)) < 0.45;
  const lift = (share: number) => mixHex(bg, dark ? "#ffffff" : "#000000", share);
  const text = look.text ?? (dark ? "#e8e6e1" : "#1a1a1a");
  const set = (name: string, value: string) => root.style.setProperty(name, value);
  set("--desk-main", bg);
  set("--desk-sidebar", look.sidebar ?? lift(dark ? -0.2 : 0.03));
  set("--desk-panel", look.panel ?? lift(0.03));
  set("--desk-raised", look.panel ? mixHex(look.panel, text, 0.03) : lift(0.06));
  set("--desk-hover", lift(0.08));
  set("--desk-head", lift(0.11));
  set("--color-surface-3", lift(0.14));
  set("--color-flyout", look.panel ?? lift(0.05));
  set("--desk-text", text);
  set("--desk-muted", look.muted ?? mixHex(text, bg, 0.42));
  set("--desk-faint", mixHex(text, bg, 0.58));
  set("--desk-line", dark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.09)");
  set("--desk-line-strong", dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.16)");
  if (look.accent) set("--desk-user", mixHex(bg, look.accent, 0.14));
  if (typeof look.radius === "number") {
    set("--radius", `${look.radius}px`); set("--radius-lg", `${look.radius + 2}px`); set("--radius-xl", `${look.radius + 4}px`);
  }
  if (look.density) set("--look-gap", look.density === "compact" ? "6px" : look.density === "spacious" ? "16px" : "10px");
  if (look.accent && !keepAccent) {
    const a = look.accent;
    [a, mixHex(a, "#ffffff", 0.25), mixHex(a, "#ffffff", 0.55), mixHex(a, "#ffffff", 0.25), a, mixHex(a, "#000000", 0.35), a]
      .forEach((v, i) => set(LOOK_ACCENT[i], v));
  }
  root.dataset.look = dark ? "dark" : "light";
}
